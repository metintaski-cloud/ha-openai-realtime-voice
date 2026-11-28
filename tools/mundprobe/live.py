# Leyla Mund LIVE Messung (28.11.2026, Stufe 2 Teil 1): haelt die Rechnung Schritt, wenn der Ton im echten Takt kommt?
#
# Die Probe (probe.py) hat gezeigt, dass Mund und Kinn aus AVTR-1 auf dem bewegten Kling Clip gut aussehen.
# Hier wird derselbe Weg so gebaut, wie er live laufen muesste, und gemessen:
#   1. VORBEREITEN (einmal je Clip, nicht live): jedes Bild des Clips anmelden und alles merken, was sich nie
#      aendert (Kopfhaltung, Ausdruck, Aussehen, Ruecksetz Matrix, Maske, der unveraendert gerechnete Kopf).
#   2. LIVE: der Ton kommt im echten Takt herein (200 ms Stuecke, das Modell braucht 200 ms Vorschau).
#      Je Stueck: Mundwerte aus der Stimme, dann fuenf Bilder mit EINEM Kopf je Bild rechnen, Maske aus dem
#      Unterschied zum gemerkten unveraenderten Kopf, in das Clip Bild setzen, vom Grafikspeicher holen.
# Gemessen wird je Stueck die Rechenzeit (erlaubt 200 ms) und je Bild, wie viel spaeter als sein Ton es fertig
# ist (um so viel muesste der Ton verzoegert werden, damit Mund und Stimme zusammenpassen).
# Kein Netz, kein Add on, kein Fernseher: nur Rechnen und zwei Videos zum Ansehen.
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
import soxr
import torch
import torch.nn.functional as F

from avtr1_renderer.avatar_loader import AvatarLoader
from avtr1_renderer.avtr1_artifact_manager import get_artifact_manager
from avtr1_renderer.components.liveportrait.motion_stitch import _transform_source
from avtr1_renderer.constants import LIPSYNC_COORDS
from avtr1_renderer.models.decoder import DecoderInput, DecoderOutput
from avtr1_renderer.models.stitch import StitchInput
from avtr1_renderer.models.warp import WarpInput
from avtr1_renderer.pipeline import Pipeline
from avtr1_renderer.types import Chunk, RenderOptions

SR = 16_000
FPS = 25
B, H = 1280, 720


def lade_ton(pfad: Path) -> np.ndarray:
    a, sr = sf.read(str(pfad), dtype="float32", always_2d=True)
    a = a.mean(axis=1)
    if sr != SR:
        a = soxr.resample(a, sr, SR, quality="HQ")
    return a.astype(np.float32)


def bilder_lesen(clip: Path, filt: str, b: int, h: int, n: int = 0, schleife: int = 0):
    cmd = ["ffmpeg", "-v", "error"]
    if schleife:
        cmd += ["-stream_loop", str(schleife)]
    cmd += ["-i", str(clip), "-an", "-vf", filt]
    if n:
        cmd += ["-frames:v", str(n)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    gr = b * h * 3
    try:
        while True:
            buf = p.stdout.read(gr)
            if len(buf) < gr:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, b, 3)
    finally:  # auch wenn der Leser frueher aufhoert: ffmpeg sauber beenden statt "Broken pipe"
        p.terminate()
        p.stdout.close()
        p.wait()


class Sprechen:
    """Je Bild 0 (Pause) bis Staerke (sie spricht). Wie in probe.py, aber nur mit dem Ton, der schon da ist."""

    def __init__(self, staerke: float):
        self.rms = np.zeros(0, dtype=np.float32)
        self.spitze = 0.0
        self.staerke = staerke

    def lerne(self, ton: np.ndarray, bekannt: int) -> None:
        schritt = SR // FPS
        neu = [float(np.sqrt(np.mean(ton[i * schritt:(i + 1) * schritt] ** 2) + 1e-12)) if i * schritt < len(ton) else 0.0
               for i in range(len(self.rms), bekannt)]
        if neu:
            self.rms = np.concatenate([self.rms, np.array(neu, dtype=np.float32)])
            self.spitze = max(self.spitze, max(neu))

    def werte(self, j0: int, j1: int) -> np.ndarray:
        lo = max(0, j0 - 12)
        r = self.rms[lo:]
        spricht = (r > 0.04 * max(self.spitze, 0.02)).astype(np.float32)
        breit = np.convolve(spricht, np.ones(9, dtype=np.float32), mode="same") > 0
        eng = np.convolve(breit.astype(np.float32), np.ones(5, dtype=np.float32), mode="same") >= 5
        w = np.convolve(eng.astype(np.float32), np.ones(5, dtype=np.float32) / 5, mode="same")
        return np.clip(w, 0.0, 1.0)[j0 - lo:j1 - lo] * self.staerke


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="/work/eingabe/tv_aermel.mp4")
    ap.add_argument("--ton", default="/work/eingabe/leyla.wav")
    ap.add_argument("--x", type=int, default=1278)
    ap.add_argument("--y", type=int, default=20)
    ap.add_argument("--punkte", default="1,2,6,12,14,17,19,20")
    ap.add_argument("--staerke", type=float, default=1.7)
    ap.add_argument("--schwelle", type=float, default=0.02)
    ap.add_argument("--name", default="live")
    ap.add_argument("--runden", type=int, default=1, help="den Ton so oft hintereinander sprechen (Dauerlauf)")
    ap.add_argument("--video", type=int, default=1, help="1 = Videos schreiben (nur bei runden 1 sinnvoll)")
    ap.add_argument("--stapel", type=int, default=5, help="so viele Koepfe gehen zusammen durch das Verzieh Netz")
    a = ap.parse_args()
    t_start = time.time()

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", a.clip], capture_output=True, text=True).stdout.strip().split(",")
    GB, GH = int(probe[0]), int(probe[1])
    print(f"LIVE MESSUNG. Clip {a.clip}: {GB} x {GH}; Ausschnitt {B} x {H} bei {a.x},{a.y}; Punkte {a.punkte}; "
          f"Staerke {a.staerke}; Runden {a.runden}; Stapel {a.stapel}", flush=True)

    ton = np.tile(lade_ton(Path(a.ton)), a.runden)
    pipeline, _ = Pipeline.from_artifacts(avatar_ids=None)
    mgr = get_artifact_manager()
    maske_pfad = mgr.get_artifact_path("pasteback_mask") if "pasteback_mask" in mgr._artifacts else None
    lader = AvatarLoader(
        engine_files={k: mgr.get_artifact_path(k) for k in
                      ("insightface_det", "landmark106", "landmark203", "appearance_extractor", "motion_extractor")},
        mask_template_path=maske_pfad, out_h=H, out_w=B, max_dim=max(H, B))
    bg_id = sorted(k for k in pipeline._backgrounds if k != "transparent")[0]
    mg = pipeline._motion_generator
    fenster = (mg.chunk_size + mg.future_size) * mg.frame_len + mg.audio_shift
    schritt = mg.chunk_size * mg.frame_len
    CS = mg.chunk_size
    n_stuecke = max(1, (len(ton) + schritt - 1) // schritt)
    n = n_stuecke * CS
    print(f"Ton {len(ton) / SR:.2f} s, {n_stuecke} Stuecke, {n} Bilder; Modelle laden dauerte {time.time() - t_start:.1f} s", flush=True)

    punkte = {int(p) for p in a.punkte.split(",")}
    flach = [f for f in LIPSYNC_COORDS if f // 3 in punkte]
    platz = [list(LIPSYNC_COORDS).index(f) for f in flach]
    flach_t = torch.tensor(flach, device="cuda")
    platz_t = torch.tensor(platz, device="cuda")
    tmp = Path("/dev/shm/leyla_bild.png")

    with torch.no_grad():
        # ------------------------------------------------------------------ 1. VORBEREITEN (einmal je Clip)
        t0 = time.time()
        clip_cpu = np.stack(list(bilder_lesen(Path(a.clip), f"fps={FPS},crop={B}:{H}:{a.x}:{a.y}", B, H)))
        N = len(clip_cpu)
        clip_gpu = torch.from_numpy(clip_cpu).cuda()                                   # (N, H, B, 3) uint8
        fs = torch.zeros((N, 32, 16, 64, 64), dtype=torch.float32, device="cuda")      # Aussehen
        xs = torch.zeros((N, 21, 3), device="cuda")
        eigen = torch.zeros((N, 63), device="cuda")                                    # eigener Ausdruck, Grundhaltung
        basis = torch.zeros((N, 21, 3), device="cuda")
        Rm = torch.zeros((N, 3, 3), device="cuda")
        skala = torch.ones((N, 1, 1), device="cuda")
        tr = torch.zeros((N, 1, 2), device="cuda")
        Mg = torch.zeros((N, 2, 3), device="cuda")
        maske = torch.zeros((N, 1, H, B), dtype=torch.float16, device="cuda")
        rgb0 = torch.zeros((N, 3, H, B), dtype=torch.uint8, device="cuda")              # unveraendert gerechneter Kopf
        gut = torch.zeros(N, dtype=torch.bool, device="cuda")
        erstes = None
        fehlt = 0
        for i in range(N):
            cv2.imwrite(str(tmp), cv2.cvtColor(clip_cpu[i], cv2.COLOR_RGB2BGR))
            try:
                av = lader.load(tmp, avatar_id="bild")
            except Exception as e:  # kein Gesicht gefunden: dieses Bild bleibt live wie im Clip
                fehlt += 1
                if fehlt <= 3:
                    print(f"Clip Bild {i}: nicht angemeldet ({type(e).__name__}: {e})", flush=True)
                continue
            if erstes is None:
                erstes = av
            kp = av.kp_info
            R = kp.R
            fs[i] = av.f_s[0]
            xs[i] = _transform_source(kp)[0]
            eigen[i] = (kp.exp.view(1, 21, 3) @ R.transpose(-1, -2)).reshape(63)
            basis[i] = (kp.kp.view(1, 21, 3) @ R)[0]
            Rm[i] = R[0]
            skala[i] = kp.scale.view(1, 1)
            tr[i] = kp.t.view(1, 3)[:, 0:2]
            Mg[i] = av.M_grid
            maske[i] = av.mask.half()
            gut[i] = True
        t_anm = time.time() - t0

        gesicht = torch.empty((CS, 3, 512, 512), dtype=torch.float32, device="cuda")

        def rechne(idx: torch.Tensor, ausdruck: torch.Tensor) -> torch.Tensor:
            """Koepfe fuer die Clip Bilder idx mit dem Ausdruck (k, 63) rechnen und ins Bild setzen: (k, 3, H, B)."""
            k = len(idx)
            x_d_roh = (basis[idx] + ausdruck.view(k, 21, 3) @ Rm[idx]) * skala[idx]
            x_d_roh[:, :, 0:2] = x_d_roh[:, :, 0:2] + tr[idx]
            xsb = xs[idx].contiguous()
            for p0 in range(0, k, a.stapel):
                p1 = min(k, p0 + a.stapel)
                x_d = pipeline._stitch(StitchInput(kp_source=xsb[p0:p1].contiguous(), kp_driving=x_d_roh[p0:p1].contiguous())).out
                verz = pipeline._warp(WarpInput(feature_3d=fs[idx[p0:p1]].contiguous(), kp_source=xsb[p0:p1].contiguous(),
                                                kp_driving=x_d.contiguous())).out
                for q in range(p1 - p0):
                    pipeline._decoder(DecoderInput(feature=verz[q:q + 1]), out=DecoderOutput(output=gesicht[p0 + q:p0 + q + 1]))
            g = gesicht[:k].clamp(0.0, 1.0)
            gitter = F.affine_grid(Mg[idx], [k, 3, H, B], align_corners=False)
            gw = F.grid_sample(g, gitter, mode="bilinear", padding_mode="border", align_corners=False)
            quelle = clip_gpu[idx].permute(0, 3, 1, 2).float() / 255.0
            return torch.lerp(quelle, gw, maske[idx].float())

        t0 = time.time()
        for i0 in range(0, N, CS):
            idx = torch.arange(i0, min(N, i0 + CS), device="cuda")
            rgb0[idx] = (rechne(idx, eigen[idx]) * 255.0 + 0.5).clamp(0, 255).byte()
        torch.cuda.synchronize()
        t_ruhe = time.time() - t0
        frei, gesamt = torch.cuda.mem_get_info()
        gemerkt = sum(t.numel() * t.element_size() for t in (clip_gpu, fs, maske, rgb0)) / 2 ** 30
        print(f"VORBEREITEN: {N} Clip Bilder, anmelden {t_anm:.1f} s ({t_anm / N * 1000:.0f} ms je Bild), unveraenderte Koepfe {t_ruhe:.1f} s; "
              f"ohne Gesicht: {fehlt}. Gemerkt je Clip {gemerkt:.2f} GB im Grafikspeicher; belegt jetzt {(gesamt - frei) / 2 ** 30:.1f} von {gesamt / 2 ** 30:.1f} GB", flush=True)

        # weicher Rand wie cv2.GaussianBlur(m, (0, 0), 9) bei Kommazahlen: Kern 73, gespiegelter Rand
        xk = torch.arange(-36, 37, device="cuda", dtype=torch.float32)
        kern = torch.exp(-(xk ** 2) / (2 * 9.0 ** 2))
        kern = kern / kern.sum()

        def weich(m: torch.Tensor) -> torch.Tensor:  # (k, 1, H, B)
            m = F.conv2d(F.pad(m, (36, 36, 0, 0), mode="reflect"), kern.view(1, 1, 1, 73))
            return F.conv2d(F.pad(m, (0, 0, 36, 36), mode="reflect"), kern.view(1, 1, 73, 1))

        # ------------------------------------------------------------------ 2. LIVE
        opt = RenderOptions(pixel_format="yuv_i420", bg_id=bg_id, stream_frames=True)
        stumm = np.zeros(fenster, dtype=np.float32)
        # Aufwaermen (zaehlt nicht): ein Stueck Mundwerte, fuenf Koepfe, einmal weich
        mg.generate_chunk(Chunk(audio_speech=stumm, audio_listen=stumm), erstes, mg.initial_state(erstes), opt)
        idx = torch.arange(0, CS, device="cuda")
        weich((rechne(idx, eigen[idx])[:, :1] > 2).float()).cpu()
        torch.cuda.synchronize()

        zustand = mg.initial_state(erstes)
        sprechen = Sprechen(a.staerke)
        speichern = bool(a.video)
        fertig = np.empty((n, H, B, 3), dtype=np.uint8) if speichern else None
        t_fertig = np.zeros(n)
        z_mund, z_kopf, z_setz, z_ges = [], [], [], []
        roh: dict[int, torch.Tensor] = {}     # Bild -> rohe Maske (H, B)
        neu_bild: dict[int, torch.Tensor] = {}  # Bild -> gerechnetes Bild (3, H, B)
        gesprochen = 0

        def abschliessen(lo: int, hi: int) -> None:
            if hi <= lo:
                return
            ms = torch.stack([torch.stack([roh[q] for q in range(max(0, j - 2), min(n, j + 3)) if q in roh]).amax(dim=0) for j in range(lo, hi)])
            m = weich(ms[:, None])
            ci = torch.tensor([j % N for j in range(lo, hi)], device="cuda")
            quelle = clip_gpu[ci].permute(0, 3, 1, 2).float()
            bild = torch.stack([neu_bild[j] for j in range(lo, hi)]) * 255.0
            aus = (quelle * (1.0 - m) + bild * m + 0.5).clamp(0, 255).byte().permute(0, 2, 3, 1).contiguous().cpu().numpy()
            jetzt = time.perf_counter() - T0
            for q, j in enumerate(range(lo, hi)):
                t_fertig[j] = jetzt
                if speichern:
                    fertig[j] = aus[q]
            for j in list(roh):
                if j < hi - 2:
                    del roh[j]
            for j in range(lo, hi):
                del neu_bild[j]

        T0 = time.perf_counter()
        for s in range(n_stuecke):
            # der Ton dieses Stuecks samt 200 ms Vorschau ist erst jetzt da (echter Takt)
            da = min(len(ton), s * schritt + fenster) / SR
            while time.perf_counter() - T0 < da:
                time.sleep(0.001)
            ta = time.perf_counter()
            st = ton[s * schritt: s * schritt + fenster]
            if len(st) < fenster:
                st = np.pad(st, (0, fenster - len(st)))
            motions, zustand = mg.generate_chunk(Chunk(audio_speech=st.astype(np.float32), audio_listen=stumm), erstes, zustand, opt)
            mund = motions.exp                                                    # (5, 39)
            torch.cuda.synchronize()
            tb = time.perf_counter()
            j0 = s * CS
            sprechen.lerne(ton, j0 + CS + mg.future_size)
            w_np = sprechen.werte(j0, j0 + CS)
            gesprochen += int((w_np > 0.5 * a.staerke).sum())
            w = torch.from_numpy(w_np.astype(np.float32)).cuda()[:, None]
            idx = torch.tensor([j % N for j in range(j0, j0 + CS)], device="cuda")
            eig = eigen[idx]
            neu = eig.clone()
            neu[:, flach_t] = (1.0 - w) * eig[:, flach_t] + w * mund[:, platz_t]
            rgb1 = rechne(idx, neu)
            unterschied = (rgb1 - rgb0[idx].float() / 255.0).abs().mean(dim=1, keepdim=True)
            m = F.max_pool2d((unterschied > a.schwelle).float(), kernel_size=31, stride=1, padding=15)
            m = m * gut[idx].float().view(CS, 1, 1, 1)
            for q in range(CS):
                roh[j0 + q] = m[q, 0]
                neu_bild[j0 + q] = rgb1[q]
            torch.cuda.synchronize()
            tc = time.perf_counter()
            abschliessen(max(0, j0 - 2), j0 + CS - 2)      # die Maske schaut 2 Bilder voraus
            td = time.perf_counter()
            z_mund.append(tb - ta)
            z_kopf.append(tc - tb)
            z_setz.append(td - tc)
            z_ges.append(td - ta)
        abschliessen(n - 2, n)
        t_live = time.perf_counter() - T0

    # ---------------------------------------------------------------------- 3. ZAHLEN
    def ms(x):
        x = np.array(x) * 1000
        return f"Mittel {x.mean():.0f}, 95 Prozent unter {np.percentile(x, 95):.0f}, Spitze {x.max():.0f} ms"

    zg = np.array(z_ges) * 1000
    spaet = t_fertig - np.arange(n) / FPS       # so viel nach seinem Ton ist das Bild fertig
    print(f"LIVE: {n} Bilder in {t_live:.1f} s Echtzeit ({len(ton) / SR:.1f} s Ton); sie spricht in {gesprochen} Bildern", flush=True)
    print(f"Je Stueck von 5 Bildern (erlaubt 200 ms): gesamt {ms(z_ges)}", flush=True)
    print(f"  davon Mundwerte: {ms(z_mund)}", flush=True)
    print(f"  davon 5 Koepfe und Maske: {ms(z_kopf)}", flush=True)
    print(f"  davon einsetzen und holen: {ms(z_setz)}", flush=True)
    print(f"Stuecke ueber 200 ms: {int((zg > 200).sum())} von {len(zg)}; Auslastung {zg.mean() / 200 * 100:.0f} Prozent", flush=True)
    print(f"Bild fertig nach seinem Ton: Mittel {spaet.mean() * 1000:.0f} ms, kleinste {spaet.min() * 1000:.0f}, groesste {spaet.max() * 1000:.0f} ms "
          f"(erste 25 Bilder ausgenommen: groesste {spaet[25:].max() * 1000:.0f} ms). So lange muesste der Ton warten.", flush=True)
    halb = len(spaet) // 2
    print(f"Laeuft es weg? groesste Verspaetung erste Haelfte {spaet[25:halb].max() * 1000:.0f} ms, zweite Haelfte {spaet[halb:].max() * 1000:.0f} ms", flush=True)

    # ---------------------------------------------------------------------- 4. VIDEOS (zaehlen nicht zur Messung)
    if speichern:
        stempel = time.strftime("%H%M%S")
        aus = Path("/work/ergebnis")
        aus.mkdir(parents=True, exist_ok=True)
        ziel4k = aus / f"leyla_live_{a.name}_{stempel}_4k.mp4"
        zielnah = aus / f"leyla_live_{a.name}_{stempel}_nah.mp4"

        def schreiber(ziel: Path, b: int, h: int):
            return subprocess.Popen(
                ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{b}x{h}", "-r", str(FPS), "-i", "-",
                 "-i", a.ton, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                 "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(ziel)],
                stdin=subprocess.PIPE)

        s4k = schreiber(ziel4k, GB, GH)
        snah = schreiber(zielnah, B * 2, H)
        def clip_im_kreis():  # dieselben N Bilder wie beim Vorbereiten, immer wieder von vorn
            while True:
                yield from bilder_lesen(Path(a.clip), f"fps={FPS}", GB, GH)

        for j, voll in zip(range(n), clip_im_kreis()):
            bild = voll.copy()
            bild[a.y:a.y + H, a.x:a.x + B] = fertig[j]
            s4k.stdin.write(bild.tobytes())
            snah.stdin.write(np.concatenate([clip_cpu[j % N], fertig[j]], axis=1).tobytes())  # links Clip, rechts live gerechnet
        for s in (s4k, snah):
            s.stdin.close()
            s.wait()
        print(f"ERGEBNIS: {ziel4k.name} und {zielnah.name}", flush=True)
    print(f"GESAMT: {time.time() - t_start:.0f} Sekunden", flush=True)


if __name__ == "__main__":
    main()
