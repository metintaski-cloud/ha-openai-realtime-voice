# Leyla Mund Probe (28.11.2026): Mund und Kinn aus AVTR-1 auf einen BEWEGTEN Kling Clip.
#
# Metins Idee: nicht ein Standbild sprechen lassen, sondern den Clip laufen lassen (Koerper, Kopf,
# Augen, Blinzeln aus dem Clip) und nur den Mund live aus der Stimme setzen.
# So geht es: AVTR-1 gibt je Bild eine Kopfdrehung und 39 Ausdruckswerte aus. Hier wird jedes Bild
# des Clips einzeln als Quelle angemeldet (eigene Kopfhaltung, eigener Ausdruck, eigenes Aussehen),
# die Kopfdrehung bleibt die des Clips, und nur die Werte der Lippen Punkte kommen aus der Stimme.
# Dann wird der Kopf zweimal gerechnet (unveraendert und mit neuem Mund); nur wo sich beide
# unterscheiden, kommt der gerechnete Mund ins Originalbild. In Sprechpausen bleibt so der Clip.
#
# Noch nicht live: das hier ist die Probe, ob es gut aussieht, und es misst, wie lange jeder Teil braucht.
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

from avtr1_renderer.avatar_loader import AvatarLoader
from avtr1_renderer.avtr1_artifact_manager import get_artifact_manager
from avtr1_renderer.components.liveportrait.motion_stitch import _transform_source
from avtr1_renderer.components.putback import putback_chunk
from avtr1_renderer.constants import LIPSYNC_COORDS
from avtr1_renderer.models.decoder import DecoderInput, DecoderOutput
from avtr1_renderer.models.stitch import StitchInput
from avtr1_renderer.models.warp import WarpInput
from avtr1_renderer.pipeline import Pipeline
from avtr1_renderer.types import Chunk, RenderOptions

SR = 16_000
FPS = 25


def lade_ton(pfad: Path) -> np.ndarray:
    a, sr = sf.read(str(pfad), dtype="float32", always_2d=True)
    a = a.mean(axis=1)
    if sr != SR:
        a = soxr.resample(a, sr, SR, quality="HQ")
    return a.astype(np.float32)


def sprech_gewicht(ton: np.ndarray, n: int) -> np.ndarray:
    """Je Bild 0 (Pause) bis 1 (sie spricht), weich an den Raendern."""
    schritt = SR // FPS
    rms = np.array([np.sqrt(np.mean(ton[i * schritt:(i + 1) * schritt] ** 2) + 1e-12) if i * schritt < len(ton) else 0.0
                    for i in range(n)], dtype=np.float32)
    spricht = (rms > 0.04 * rms.max()).astype(np.float32)
    # Luecken unter 0,3 s zaehlen zum Sprechen, Beginn 2 Bilder frueher, Ende 2 Bilder spaeter
    breit = np.convolve(spricht, np.ones(9, dtype=np.float32), mode="same") > 0
    eng = np.convolve(breit.astype(np.float32), np.ones(5, dtype=np.float32), mode="same") >= 5
    w = np.convolve(eng.astype(np.float32), np.ones(5, dtype=np.float32) / 5, mode="same")
    return np.clip(w, 0.0, 1.0)


def bilder_lesen(clip: Path, n: int, filt: str, b: int, h: int):
    cmd = ["ffmpeg", "-v", "error", "-stream_loop", "3", "-i", str(clip), "-an", "-vf", filt,
           "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    gr = b * h * 3
    for _ in range(n):
        buf = p.stdout.read(gr)
        if len(buf) < gr:
            break
        yield np.frombuffer(buf, dtype=np.uint8).reshape(h, b, 3)
    p.stdout.close()
    p.wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="/work/eingabe/tv_aermel.mp4")
    ap.add_argument("--ton", default="/work/eingabe/leyla.wav")
    ap.add_argument("--x", type=int, default=1278)
    ap.add_argument("--y", type=int, default=20)
    ap.add_argument("--punkte", default="6,12,14,17,19,20", help="Ausdruckspunkte, die aus der Stimme kommen")
    ap.add_argument("--staerke", type=float, default=1.0, help="wie stark der Mund der Stimme folgt")
    ap.add_argument("--schwelle", type=float, default=0.02)
    ap.add_argument("--name", default="lippen")
    ap.add_argument("--bilder", type=int, default=0, help="nur so viele Bilder rechnen (0 = alle)")
    a = ap.parse_args()
    B, H = 1280, 720
    t_start = time.time()

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", a.clip], capture_output=True, text=True).stdout.strip().split(",")
    GB, GH = int(probe[0]), int(probe[1])
    print(f"Clip {a.clip}: {GB} x {GH}; Ausschnitt {B} x {H} bei {a.x},{a.y}; Punkte {a.punkte}; Staerke {a.staerke}", flush=True)

    ton = lade_ton(Path(a.ton))
    pipeline, _ = Pipeline.from_artifacts(avatar_ids=None)
    mgr = get_artifact_manager()
    maske_pfad = mgr.get_artifact_path("pasteback_mask") if "pasteback_mask" in mgr._artifacts else None
    lader = AvatarLoader(
        engine_files={k: mgr.get_artifact_path(k) for k in
                      ("insightface_det", "landmark106", "landmark203", "appearance_extractor", "motion_extractor")},
        mask_template_path=maske_pfad, out_h=H, out_w=B, max_dim=max(H, B))
    bg_id = sorted(k for k in pipeline._backgrounds if k != "transparent")[0]
    bg = pipeline._backgrounds[bg_id]
    mg = pipeline._motion_generator
    fenster = (mg.chunk_size + mg.future_size) * mg.frame_len + mg.audio_shift
    schritt = mg.chunk_size * mg.frame_len
    n_stuecke = max(1, (len(ton) + schritt - 1) // schritt)
    n = n_stuecke * mg.chunk_size
    if a.bilder:
        n = min(n, a.bilder)
    print(f"Ton {len(ton) / SR:.2f} s, {n_stuecke} Stuecke, {n} Bilder; Laden dauerte {time.time() - t_start:.1f} s", flush=True)

    # 1. Kopf Ausschnitt aller Bilder (der Clip laeuft als Schleife weiter, wenn der Ton laenger ist)
    ausschnitte = list(bilder_lesen(Path(a.clip), n, f"fps={FPS},crop={B}:{H}:{a.x}:{a.y}", B, H))
    n = min(n, len(ausschnitte))
    tmp = Path("/dev/shm/leyla_bild.png")

    def anmelden(i: int):
        cv2.imwrite(str(tmp), cv2.cvtColor(ausschnitte[i], cv2.COLOR_RGB2BGR))
        return lader.load(tmp, avatar_id="bild")

    with torch.no_grad():
        # 2. Mundwerte aus der Stimme (einmal, mit dem ersten Bild als Bezug)
        t0 = time.time()
        erstes = anmelden(0)
        opt = RenderOptions(pixel_format="yuv_i420", bg_id=bg_id, stream_frames=True)
        zustand = mg.initial_state(erstes)
        stumm = np.zeros(fenster, dtype=np.float32)
        mund = []
        for s in range(n_stuecke):
            st = ton[s * schritt: s * schritt + fenster]
            if len(st) < fenster:
                st = np.pad(st, (0, fenster - len(st)))
            motions, zustand = mg.generate_chunk(Chunk(audio_speech=st.astype(np.float32), audio_listen=stumm), erstes, zustand, opt)
            mund.append(motions.exp.clone())
        mund = torch.cat(mund, dim=0)[:n]  # (n, 39) Werte in der Reihenfolge von LIPSYNC_COORDS
        t_mund = (time.time() - t0) / max(1, n_stuecke) * 1000
        print(f"Mundwerte: {t_mund:.0f} ms je Stueck von 5 Bildern", flush=True)

        punkte = {int(p) for p in a.punkte.split(",")}
        flach = [f for f in LIPSYNC_COORDS if f // 3 in punkte]
        platz = [list(LIPSYNC_COORDS).index(f) for f in flach]
        flach_t = torch.tensor(flach, device="cuda")
        platz_t = torch.tensor(platz, device="cuda")
        gewicht = sprech_gewicht(ton, n) * a.staerke
        print(f"{len(flach)} von 63 Ausdruckswerten kommen aus der Stimme; sie spricht in {int((gewicht > 0.5).sum())} von {n} Bildern", flush=True)

        # 3. Je Bild: anmelden, Kopf unveraendert und mit neuem Mund rechnen
        ergebnis = np.empty((n, H, B, 3), dtype=np.uint8)
        masken = np.zeros((n, H, B), dtype=np.float32)
        t_anm = t_rech = 0.0
        fehlt = 0
        gesicht = torch.empty((2, 3, 512, 512), dtype=torch.float32, device="cuda")
        for j in range(n):
            t0 = time.time()
            try:
                av = anmelden(j)
            except Exception as e:  # kein Gesicht gefunden: Bild bleibt wie im Clip
                fehlt += 1
                ergebnis[j] = ausschnitte[j]
                if fehlt <= 3:
                    print(f"Bild {j}: nicht angemeldet ({type(e).__name__}: {e})", flush=True)
                continue
            t1 = time.time()
            kp = av.kp_info
            R = kp.R
            kpc = kp.kp.view(1, 21, 3)
            x_s = _transform_source(kp)
            # eigener Ausdruck des Bilds, zurueckgedreht in die Grundhaltung (so rechnet das Modell)
            eigen = (kp.exp.view(1, 21, 3) @ R.transpose(-1, -2)).reshape(1, 63)
            neu = eigen.clone()
            w = float(gewicht[j])
            neu[0, flach_t] = (1.0 - w) * eigen[0, flach_t] + w * mund[j, platz_t]
            x_d_roh = (kpc @ R + neu.view(1, 21, 3) @ R) * kp.scale[..., None]
            x_d_roh[:, :, 0:2] = x_d_roh[:, :, 0:2] + kp.t[:, None, 0:2]
            x_s2 = x_s.expand(2, -1, -1).contiguous()
            x_d = pipeline._stitch(StitchInput(kp_source=x_s2, kp_driving=torch.cat([x_s, x_d_roh], dim=0).contiguous())).out
            f2 = av.f_s.expand(2, -1, -1, -1, -1).contiguous()
            verzogen = pipeline._warp(WarpInput(feature_3d=f2, kp_source=x_s2, kp_driving=x_d.contiguous())).out
            for k in range(2):
                pipeline._decoder(DecoderInput(feature=verzogen[k:k + 1]), out=DecoderOutput(output=gesicht[k:k + 1]))
            gesicht.clamp_(0.0, 1.0)
            rgb, _ = putback_chunk(gesicht, av, bg, matting=pipeline._matting)  # (2, 3, H, B): unveraendert, neuer Mund
            unterschied = (rgb[1] - rgb[0]).abs().mean(dim=0)
            m = (unterschied > a.schwelle).float()[None, None]
            m = torch.nn.functional.max_pool2d(m, kernel_size=31, stride=1, padding=15)
            masken[j] = m[0, 0].cpu().numpy()
            ergebnis[j] = (rgb[1].permute(1, 2, 0) * 255.0 + 0.5).clamp(0, 255).byte().cpu().numpy()
            torch.cuda.synchronize()
            t_anm += t1 - t0
            t_rech += time.time() - t1
            if j % 50 == 0:
                print(f"Bild {j}/{n}", flush=True)
        ok = max(1, n - fehlt)
        print(f"Je Bild: anmelden {t_anm / ok * 1000:.0f} ms, rechnen (zwei Koepfe) {t_rech / ok * 1000:.0f} ms; "
              f"ohne Gesicht: {fehlt} Bilder. Live braucht hoechstens 40 ms je Bild.", flush=True)

    # 4. Masken ueber die Zeit glaetten (kein Flackern), Raender weich
    weich = np.empty_like(masken)
    for j in range(n):
        m = masken[max(0, j - 2): j + 3].max(axis=0)
        weich[j] = cv2.GaussianBlur(m, (0, 0), 9)
    anteil = float((weich > 0.5).mean()) * 100
    print(f"Ersetzte Flaeche im Mittel {anteil:.2f} Prozent des Ausschnitts", flush=True)

    # 5. Zusammensetzen: 4K Totale und Nahansicht (nur der Ausschnitt)
    stempel = time.strftime("%H%M%S")
    aus = Path("/work/ergebnis")
    aus.mkdir(parents=True, exist_ok=True)
    ziel4k = aus / f"leyla_probe_{a.name}_{stempel}_4k.mp4"
    zielnah = aus / f"leyla_probe_{a.name}_{stempel}_nah.mp4"

    def schreiber(ziel: Path, b: int, h: int):
        return subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{b}x{h}", "-r", str(FPS), "-i", "-",
             "-i", a.ton, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(ziel)],
            stdin=subprocess.PIPE)

    s4k = schreiber(ziel4k, GB, GH)
    snah = schreiber(zielnah, B * 2, H)
    for j, voll in enumerate(bilder_lesen(Path(a.clip), n, f"fps={FPS}", GB, GH)):
        m = weich[j][..., None]
        neu = (ausschnitte[j].astype(np.float32) * (1.0 - m) + ergebnis[j].astype(np.float32) * m + 0.5).astype(np.uint8)
        bild = voll.copy()
        bild[a.y:a.y + H, a.x:a.x + B] = neu
        s4k.stdin.write(bild.tobytes())
        snah.stdin.write(np.concatenate([ausschnitte[j], neu], axis=1).tobytes())  # links Clip, rechts mit Mund
    for s in (s4k, snah):
        s.stdin.close()
        s.wait()
    print(f"ERGEBNIS: {ziel4k.name} und {zielnah.name}", flush=True)
    print(f"GESAMT: {time.time() - t_start:.0f} Sekunden", flush=True)


if __name__ == "__main__":
    main()
