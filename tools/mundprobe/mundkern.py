# Leyla Mundkern (28.11.2026): der Rechenteil "Mund und Kinn aus AVTR-1 auf dem bewegten Clip" als Baustein.
#
# Derselbe Weg wie in live.py (dort gemessen: 115 bis 120 ms je 200 ms Stueck auf der RTX 4070 Ti), nur als
# Klasse, damit ein Dienst ihn benutzen kann:
#   kern = MundKern(clip, x, y)          Modelle laden und den Clip einmal vorbereiten (rund 30 s)
#   rede = kern.neue_rede(versatz)       eine Rede beginnen; versatz = Clip Bild, das beim ersten Ton Bild laeuft
#   rede.fuettern(ton), rede.ende()      der Ton trifft nach und nach ein (16 kHz), dann ist er zu Ende
#   rede.kann(s), rede.rechne_stueck(s)  Stueck s (5 Bilder) rechnen, sobald genug Ton da ist; gibt die fertigen Bilder zurueck
#   rede.schluss()                       die letzten zwei Bilder
# Fertige Bilder sind der Kopf Ausschnitt in halber Groesse (640 x 360, passend fuer ein Full HD Bild).
# Alles hier muss im selben Thread laufen (ein Grafikkarten Zusammenhang).
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
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


def bilder_lesen(clip: Path, filt: str, b: int, h: int):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(clip), "-an", "-vf", filt, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    gr = b * h * 3
    try:
        while True:
            buf = p.stdout.read(gr)
            if len(buf) < gr:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, b, 3)
    finally:
        p.terminate()
        p.stdout.close()
        p.wait()


class Sprechen:
    """Je Bild 0 (Pause) bis Staerke (sie spricht); arbeitet nur mit dem Ton, der schon da ist."""

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


class MundKern:
    def __init__(self, clip: str, x: int = 1278, y: int = 20, punkte: str = "1,2,6,12,14,17,19,20",
                 staerke: float = 1.7, schwelle: float = 0.02, melde=print):
        self.staerke, self.schwelle = staerke, schwelle
        t0 = time.time()
        self.pipeline, _ = Pipeline.from_artifacts(avatar_ids=None)
        mgr = get_artifact_manager()
        maske_pfad = mgr.get_artifact_path("pasteback_mask") if "pasteback_mask" in mgr._artifacts else None
        lader = AvatarLoader(
            engine_files={k: mgr.get_artifact_path(k) for k in
                          ("insightface_det", "landmark106", "landmark203", "appearance_extractor", "motion_extractor")},
            mask_template_path=maske_pfad, out_h=H, out_w=B, max_dim=max(H, B))
        bg_id = sorted(k for k in self.pipeline._backgrounds if k != "transparent")[0]
        self.opt = RenderOptions(pixel_format="yuv_i420", bg_id=bg_id, stream_frames=True)
        self.mg = mg = self.pipeline._motion_generator
        self.CS = mg.chunk_size
        self.voraus = mg.chunk_size + mg.future_size            # so viele Ton Bilder braucht ein Stueck ab seinem Anfang
        self.fenster = (mg.chunk_size + mg.future_size) * mg.frame_len + mg.audio_shift
        self.schritt = mg.chunk_size * mg.frame_len
        self.stumm = np.zeros(self.fenster, dtype=np.float32)
        pk = {int(p) for p in punkte.split(",")}
        flach = [f for f in LIPSYNC_COORDS if f // 3 in pk]
        self.flach_t = torch.tensor(flach, device="cuda")
        self.platz_t = torch.tensor([list(LIPSYNC_COORDS).index(f) for f in flach], device="cuda")
        melde(f"Modelle geladen in {time.time() - t0:.1f} s")

        with torch.no_grad():
            t0 = time.time()
            clip_cpu = np.stack(list(bilder_lesen(Path(clip), f"fps={FPS},crop={B}:{H}:{x}:{y}", B, H)))
            self.N = N = len(clip_cpu)
            self.clip_gpu = torch.from_numpy(clip_cpu).cuda()
            self.fs = torch.zeros((N, 32, 16, 64, 64), dtype=torch.float32, device="cuda")
            self.xs = torch.zeros((N, 21, 3), device="cuda")
            self.eigen = torch.zeros((N, 63), device="cuda")
            self.basis = torch.zeros((N, 21, 3), device="cuda")
            self.Rm = torch.zeros((N, 3, 3), device="cuda")
            self.skala = torch.ones((N, 1, 1), device="cuda")
            self.tr = torch.zeros((N, 1, 2), device="cuda")
            self.Mg = torch.zeros((N, 2, 3), device="cuda")
            self.maske = torch.zeros((N, 1, H, B), dtype=torch.float16, device="cuda")
            self.rgb0 = torch.zeros((N, 3, H, B), dtype=torch.uint8, device="cuda")
            self.gut = torch.zeros(N, dtype=torch.bool, device="cuda")
            self.erstes = None
            fehlt = 0
            tmp = Path("/dev/shm/leyla_bild.png")
            for i in range(N):
                cv2.imwrite(str(tmp), cv2.cvtColor(clip_cpu[i], cv2.COLOR_RGB2BGR))
                try:
                    av = lader.load(tmp, avatar_id="bild")
                except Exception:  # kein Gesicht gefunden: dieses Bild bleibt wie im Clip
                    fehlt += 1
                    continue
                if self.erstes is None:
                    self.erstes = av
                kp = av.kp_info
                R = kp.R
                self.fs[i] = av.f_s[0]
                self.xs[i] = _transform_source(kp)[0]
                self.eigen[i] = (kp.exp.view(1, 21, 3) @ R.transpose(-1, -2)).reshape(63)
                self.basis[i] = (kp.kp.view(1, 21, 3) @ R)[0]
                self.Rm[i] = R[0]
                self.skala[i] = kp.scale.view(1, 1)
                self.tr[i] = kp.t.view(1, 3)[:, 0:2]
                self.Mg[i] = av.M_grid
                self.maske[i] = av.mask.half()
                self.gut[i] = True
            del clip_cpu
            self.gesicht = torch.empty((self.CS, 3, 512, 512), dtype=torch.float32, device="cuda")
            for i0 in range(0, N, self.CS):
                idx = torch.arange(i0, min(N, i0 + self.CS), device="cuda")
                self.rgb0[idx] = (self.rechne(idx, self.eigen[idx]) * 255.0 + 0.5).clamp(0, 255).byte()
            xk = torch.arange(-36, 37, device="cuda", dtype=torch.float32)
            kern = torch.exp(-(xk ** 2) / (2 * 9.0 ** 2))
            self.kern = kern / kern.sum()
            # Aufwaermen
            self.mg.generate_chunk(Chunk(audio_speech=self.stumm, audio_listen=self.stumm), self.erstes, self.mg.initial_state(self.erstes), self.opt)
            idx = torch.arange(0, self.CS, device="cuda")
            self.weich((self.rechne(idx, self.eigen[idx])[:, :1] > 2).float()).cpu()
            torch.cuda.synchronize()
            frei, gesamt = torch.cuda.mem_get_info()
        melde(f"Clip vorbereitet: {N} Bilder in {time.time() - t0:.1f} s, ohne Gesicht {fehlt}; Grafikspeicher belegt {(gesamt - frei) / 2 ** 30:.1f} von {gesamt / 2 ** 30:.1f} GB")

    def rechne(self, idx: torch.Tensor, ausdruck: torch.Tensor) -> torch.Tensor:
        """Koepfe fuer die Clip Bilder idx mit dem Ausdruck (k, 63) rechnen und ins Bild setzen: (k, 3, H, B)."""
        k = len(idx)
        x_d_roh = (self.basis[idx] + ausdruck.view(k, 21, 3) @ self.Rm[idx]) * self.skala[idx]
        x_d_roh[:, :, 0:2] = x_d_roh[:, :, 0:2] + self.tr[idx]
        xsb = self.xs[idx].contiguous()
        x_d = self.pipeline._stitch(StitchInput(kp_source=xsb, kp_driving=x_d_roh.contiguous())).out
        verz = self.pipeline._warp(WarpInput(feature_3d=self.fs[idx].contiguous(), kp_source=xsb, kp_driving=x_d.contiguous())).out
        for q in range(k):
            self.pipeline._decoder(DecoderInput(feature=verz[q:q + 1]), out=DecoderOutput(output=self.gesicht[q:q + 1]))
        g = self.gesicht[:k].clamp(0.0, 1.0)
        gitter = F.affine_grid(self.Mg[idx], [k, 3, H, B], align_corners=False)
        gw = F.grid_sample(g, gitter, mode="bilinear", padding_mode="border", align_corners=False)
        quelle = self.clip_gpu[idx].permute(0, 3, 1, 2).float() / 255.0
        return torch.lerp(quelle, gw, self.maske[idx].float())

    def weich(self, m: torch.Tensor) -> torch.Tensor:
        """Weicher Rand wie cv2.GaussianBlur(m, (0, 0), 9): Kern 73, gespiegelter Rand. m: (k, 1, H, B)."""
        m = F.conv2d(F.pad(m, (36, 36, 0, 0), mode="reflect"), self.kern.view(1, 1, 1, 73))
        return F.conv2d(F.pad(m, (0, 0, 36, 36), mode="reflect"), self.kern.view(1, 1, 73, 1))

    def neue_rede(self, versatz: int, ton: np.ndarray | None = None) -> "Rede":
        """Eine Rede beginnen. Mit ton ist der ganze Satz schon da (Test); ohne kommt er Stueck fuer Stueck ueber fuettern()."""
        rede = Rede(self, versatz)
        if ton is not None:
            rede.fuettern(ton)
            rede.ende()
        return rede


class Rede:
    """Eine Rede mit fortlaufend eintreffendem Ton (16 kHz, float). Bild j der Rede gehoert zu Clip Bild versatz + j."""

    def __init__(self, kern: MundKern, versatz: int):
        self.k, self.versatz = kern, versatz
        self.ton = np.zeros(0, dtype=np.float32)
        self.zu = False                      # True: es kommt kein Ton mehr
        with torch.no_grad():
            self.zustand = kern.mg.initial_state(kern.erstes)
        self.sprechen = Sprechen(kern.staerke)
        self.roh: dict[int, torch.Tensor] = {}
        self.neu_bild: dict[int, torch.Tensor] = {}
        self.zeiten: list[float] = []

    def fuettern(self, st: np.ndarray) -> None:
        self.ton = np.concatenate([self.ton, st.astype(np.float32)])

    def ende(self) -> None:
        self.zu = True

    @property
    def stuecke(self) -> int:                # endgueltig erst nach ende()
        return max(1, (len(self.ton) + self.k.schritt - 1) // self.k.schritt)

    @property
    def n(self) -> int:
        return self.stuecke * self.k.CS

    def kann(self, s: int) -> bool:
        """Ist genug Ton da, um Stueck s zu rechnen (das Modell braucht 200 ms Vorschau)?"""
        return len(self.ton) >= s * self.k.schritt + self.k.fenster or (self.zu and s < self.stuecke)

    def _idx(self, lo: int, hi: int) -> torch.Tensor:
        return torch.tensor([(self.versatz + j) % self.k.N for j in range(lo, hi)], device="cuda")

    def _abschliessen(self, lo: int, hi: int) -> dict[int, np.ndarray]:
        if hi <= lo:
            return {}
        k = self.k
        ms = torch.stack([torch.stack([self.roh[q] for q in range(max(0, j - 2), min(self.n, j + 3)) if q in self.roh]).amax(dim=0)
                          for j in range(lo, hi)])
        m = k.weich(ms[:, None])
        quelle = k.clip_gpu[self._idx(lo, hi)].permute(0, 3, 1, 2).float()
        bild = torch.stack([self.neu_bild[j] for j in range(lo, hi)]) * 255.0
        gross = quelle * (1.0 - m) + bild * m
        klein = (F.avg_pool2d(gross, 2) + 0.5).clamp(0, 255).byte().permute(0, 2, 3, 1).contiguous().cpu().numpy()
        for j in list(self.roh):
            if j < hi - 2:
                del self.roh[j]
        for j in range(lo, hi):
            del self.neu_bild[j]
        return {j: klein[q] for q, j in enumerate(range(lo, hi))}

    def rechne_stueck(self, s: int) -> dict[int, np.ndarray]:
        k = self.k
        ta = time.perf_counter()
        with torch.no_grad():
            st = self.ton[s * k.schritt: s * k.schritt + k.fenster]
            if len(st) < k.fenster:
                st = np.pad(st, (0, k.fenster - len(st)))
            motions, self.zustand = k.mg.generate_chunk(Chunk(audio_speech=st.astype(np.float32), audio_listen=k.stumm), k.erstes, self.zustand, k.opt)
            mund = motions.exp
            j0 = s * k.CS
            self.sprechen.lerne(self.ton, j0 + k.voraus)
            w = torch.from_numpy(self.sprechen.werte(j0, j0 + k.CS).astype(np.float32)).cuda()[:, None]
            idx = self._idx(j0, j0 + k.CS)
            eig = k.eigen[idx]
            neu = eig.clone()
            neu[:, k.flach_t] = (1.0 - w) * eig[:, k.flach_t] + w * mund[:, k.platz_t]
            rgb1 = k.rechne(idx, neu)
            unterschied = (rgb1 - k.rgb0[idx].float() / 255.0).abs().mean(dim=1, keepdim=True)
            m = F.max_pool2d((unterschied > k.schwelle).float(), kernel_size=31, stride=1, padding=15)
            m = m * k.gut[idx].float().view(k.CS, 1, 1, 1)
            for q in range(k.CS):
                self.roh[j0 + q] = m[q, 0]
                self.neu_bild[j0 + q] = rgb1[q]
            aus = self._abschliessen(max(0, j0 - 2), j0 + k.CS - 2)   # die Maske schaut 2 Bilder voraus
        self.zeiten.append(time.perf_counter() - ta)
        return aus

    def schluss(self) -> dict[int, np.ndarray]:
        with torch.no_grad():
            return self._abschliessen(self.n - 2, self.n)
