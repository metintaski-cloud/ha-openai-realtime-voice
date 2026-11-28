# Leyla Vorfuehrung (28.11.2026, Stufe 2 Teil 3): Leyla spricht am Fernseher einen Satz, LIVE gerechnet.
#
# Verbindet die zwei geprueften Teile: den Rechenteil (mundkern.py: Mund und Kinn aus der Stimme auf dem
# bewegten Clip) und den Strom zum Fernseher (wie strom.py: ein laufendes Video in Full HD ueber Port 8090).
# Ablauf: der Clip laeuft als Schleife. Alle paar Sekunden "kommt" Leylas Satz im echten Takt herein
# (eingabe/leyla.wav), der Mund wird Stueck fuer Stueck gerechnet, und Bild und Ton gehen gemeinsam in den
# Strom: der Ton genau so viel spaeter, wie das Rechnen braucht (VERSATZ Bilder). Im Strom sitzen Bild und Ton
# fest aufeinander, der Browser haelt sie zusammen.
# In dieser Vorfuehrung kommt Leylas Stimme deshalb aus dem FERNSEHER, nicht aus der Voice PE.
#   /            Seite (Vollbild Video; ?info=1 zeigt die Messzeile, ?stumm=1 laesst den Ton aus)
#   /strom.mp4   das Bild (H.264, fragmentiertes MP4)
#   /ton.mp4     der Ton dazu (AAC, eigener Strom mit derselben Uhr; die Seite fuegt beide zusammen)
#   /bericht     Meldungen der Seite
# Datei avtr/sprich.txt anlegen: sie spricht sofort. Datei avtr/vorfuehrung_ende.txt: beenden.
# Mit --attrappe laeuft alles ohne Modelle (ein helles Feld statt des Munds), um Strom, Ton und Seite zu pruefen.
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

B, H, FPS, SR = 1920, 1080, 25, 16_000
PORT = 8090
FELD, RAND = 24, 8
VERSATZ = 20                 # so viele Bilder (0,8 s) nach dem Eintreffen des Tons erscheinen Bild und Ton im Strom
RX, RY, RB, RH = 640, 10, 640, 360   # der Kopf Ausschnitt im Full HD Bild (4K: 1278,20 und 1280 x 720; 1 Punkt Rand links)
ORT = Path(__file__).resolve().parent
LOG = ORT / "vorfuehrung_log.txt"
ENDE = ORT / "vorfuehrung_ende.txt"
SPRICH = ORT / "sprich.txt"

sperre = threading.Lock()
gesendet = [0.0] * 65536
KODIERER = {  # x264 im Prozessor (auf Metins PC im Strom Test geprueft), nvenc auf der Grafikkarte, schnell nur fuer schwache Rechner
    "x264": ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "main", "-level", "4.0", "-crf", "20", "-maxrate", "12M", "-bufsize", "6M"],
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-profile:v", "main", "-level", "4.0", "-rc", "vbr", "-cq", "23", "-maxrate", "12M", "-bufsize", "6M"],
    "schnell": ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "23"],
}


def log(text: str) -> None:
    zeile = time.strftime("%H:%M:%S ") + text
    print(zeile, flush=True)
    with sperre, LOG.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")


def lade_ton(pfad: str) -> np.ndarray:
    roh = subprocess.run(["ffmpeg", "-v", "error", "-i", pfad, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(roh, dtype=np.float32).copy()


def lade_clip(clip: str, x: int) -> np.ndarray:
    """Der ganze Clip in Full HD im Arbeitsspeicher: genau halbe Groesse (Flaechenmittel), 1 Punkt Rand links und rechts."""
    breit = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "csv=p=0", clip],
                           capture_output=True, text=True).stdout.strip()
    halb = int(breit) // 2
    rand = (B - halb) // 2
    assert rand + x // 2 == RX, f"Ausschnitt passt nicht: Rand {rand}, x {x}"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", clip, "-an", "-vf", f"fps={FPS},scale={halb}:{H}:flags=area,pad={B}:{H}:{rand}:0",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    bilder = []
    gr = B * H * 3
    while True:
        buf = p.stdout.read(gr)
        if len(buf) < gr:
            break
        bilder.append(np.frombuffer(buf, dtype=np.uint8).reshape(H, B, 3))
    p.wait()
    return np.stack(bilder)


class AttrappeRede:
    """Ohne Modelle: statt des Munds ein helles Feld, dessen Groesse der Lautstaerke folgt. Nur zum Pruefen des Wegs."""

    def __init__(self, kern, ton, versatz):
        self.k, self.ton, self.versatz = kern, ton, versatz
        self.stuecke = max(1, (len(ton) + kern.schritt - 1) // kern.schritt)
        self.n = self.stuecke * kern.CS
        self.zeiten: list[float] = []

    def _bild(self, j):
        reg = self.k.clip[(self.versatz + j) % self.k.N, RY:RY + RH, RX:RX + RB].copy()
        st = self.ton[j * 640:(j + 1) * 640]
        laut = float(np.sqrt(np.mean(st ** 2))) if len(st) else 0.0
        g = int(min(60, 4 + laut * 600))
        reg[180 - g:180 + g, 320 - g:320 + g] = 255
        return reg

    def rechne_stueck(self, s):
        time.sleep(0.11)
        self.zeiten.append(0.11)
        j0 = s * self.k.CS
        return {j: self._bild(j) for j in range(max(0, j0 - 2), j0 + self.k.CS - 2)}

    def schluss(self):
        return {j: self._bild(j) for j in range(self.n - 2, self.n)}


class Attrappe:
    CS, voraus, schritt = 5, 10, 3200

    def __init__(self, clip: np.ndarray):
        self.clip, self.N = clip, len(clip)

    def neue_rede(self, ton, versatz):
        return AttrappeRede(self, ton, versatz)


class Buehne:
    """Haelt den Takt: ein Bild alle 40 ms. Rechnen (eigener Thread) und Senden (eigener Thread) teilen sich diesen Stand."""

    def __init__(self, a):
        self.a = a
        self.clip = None
        self.kern = None
        self.ton = None
        self.bereit = threading.Event()
        self.pos = 0                 # Bild Nummer der Buehne, laeuft immer weiter
        self.rede = None             # {"A", "obj", "fertig", "s", "zu", "spaet", "gezeigt"}
        self.wunsch = None           # Bild Nummer, bei der der Ton der naechsten Rede eintrifft
        self.naechste = 0
        self.zuschauer = None        # {"enc", "ton", "n", "kennung", "ton_raus"}
        self.klappe = threading.Lock()

    # ---------------------------------------------------------------- Rechnen (einziger Thread mit der Grafikkarte)
    def rechner(self) -> None:
        try:
            self._rechner()
        except Exception:  # sonst stirbt der Thread still und niemand erfaehrt, warum nichts kommt
            import traceback
            log("FEHLER im Rechner: " + traceback.format_exc().replace("\n", " | "))

    def _rechner(self) -> None:
        a = self.a
        self.ton = lade_ton(a.ton)
        self.clip = lade_clip(a.clip, a.x)
        log(f"Clip in Full HD geladen: {len(self.clip)} Bilder; Satz {len(self.ton) / SR:.1f} s")
        if a.attrappe:
            self.kern = Attrappe(self.clip)
        else:
            from mundkern import MundKern
            self.kern = MundKern(a.clip, a.x, a.y, a.punkte, a.staerke, a.schwelle, melde=log)
        assert self.kern.N == len(self.clip), f"Clip Laengen verschieden: {self.kern.N} und {len(self.clip)}"
        self.naechste = self.pos + int(a.pause * FPS)
        self.bereit.set()
        log(f"BEREIT auf Port {PORT}. Dieses Fenster offen lassen.")
        k = self.kern
        while True:
            with self.klappe:
                w, r = self.wunsch, self.rede
            if w is not None and r is None:
                obj = k.neue_rede(self.ton, w + VERSATZ)
                with self.klappe:
                    self.rede = {"A": w, "obj": obj, "fertig": {}, "s": 0, "zu": False, "spaet": 0, "gezeigt": 0}
                    self.wunsch = None
                continue
            if r is None:
                time.sleep(0.005)
                continue
            obj = r["obj"]
            if r["s"] >= obj.stuecke:
                if not r["zu"]:
                    aus = obj.schluss()
                    with self.klappe:
                        r["fertig"].update(aus)
                        r["zu"] = True
                time.sleep(0.005)
                continue
            angekommen = self.pos - r["A"]                       # so viele Ton Bilder sind schon da (echter Takt)
            noetig = min(obj.n, r["s"] * k.CS + k.voraus + 1)
            if angekommen < noetig:
                time.sleep(0.002)
                continue
            aus = obj.rechne_stueck(r["s"])
            with self.klappe:
                r["fertig"].update(aus)
                r["s"] += 1

    # ---------------------------------------------------------------- Senden (ein Bild alle 40 ms)
    def sender(self) -> None:
        self.bereit.wait()
        stille = bytes(1280)
        t0 = time.perf_counter()
        start = self.pos
        while True:
            warte = t0 + (self.pos - start) / FPS - time.perf_counter()
            if warte > 0:
                time.sleep(warte)
            elif warte < -0.5:                                   # weit hinterher (z. B. der Zuschauer liest nicht): Takt neu setzen
                t0, start = time.perf_counter(), self.pos
            p = self.pos
            with self.klappe:
                z, r = self.zuschauer, self.rede
                if r is None and self.wunsch is None and z is not None and p % 5 == 0 and (p >= self.naechste or SPRICH.exists()):
                    self.wunsch = p
                    SPRICH.unlink(missing_ok=True)
            bild = None
            ton = stille
            if r is not None:
                j = p - r["A"] - VERSATZ
                if 0 <= j < r["obj"].n:
                    with self.klappe:
                        reg = r["fertig"].pop(j, None)
                    if reg is not None:
                        bild = self.clip[p % len(self.clip)].copy()
                        bild[RY:RY + RH, RX:RX + RB] = reg
                        r["gezeigt"] += 1
                    else:
                        r["spaet"] += 1
                    st = self.ton[j * 640:(j + 1) * 640]
                    if len(st):
                        ton = (np.clip(np.pad(st, (0, 640 - len(st))), -1, 1) * 32767).astype("<i2").tobytes()
                elif j >= r["obj"].n:
                    zt = np.array(r["obj"].zeiten) * 1000
                    log(f"REDE fertig: {r['gezeigt']} Bilder mit live gerechnetem Mund, zu spaet gekommen {r['spaet']}; "
                        f"Rechnen je Stueck Mittel {zt.mean():.0f} ms, Spitze {zt.max():.0f} ms (erlaubt 200)")
                    with self.klappe:
                        self.rede = None
                        self.naechste = p + int(self.a.pause * FPS)
            if z is not None:
                if bild is None:
                    bild = self.clip[p % len(self.clip)].copy()
                n = z["n"]
                bits = [(n >> (15 - i)) & 1 for i in range(16)] + [1, 0, 1, 0]
                if self.a.marke:
                    for i, bit in enumerate(bits):
                        bild[RAND:RAND + FELD, RAND + i * FELD:RAND + (i + 1) * FELD] = 235 if bit else 16
                try:
                    gesendet[n & 0xFFFF] = time.time()
                    z["ton"].put(ton)
                    z["enc"].stdin.write(bild.tobytes())
                    z["enc"].stdin.flush()
                    z["n"] = n + 1
                except (BrokenPipeError, OSError):
                    with self.klappe:
                        if self.zuschauer is z:
                            self.zuschauer = None
            self.pos = p + 1


buehne: Buehne | None = None

SEITE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Leyla live</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;background:#000;overflow:hidden}video{width:100vw;height:100vh;object-fit:contain;background:#000}
#info{position:fixed;left:12px;bottom:10px;color:#7f7;font:18px monospace;background:rgba(0,0,0,.55);padding:4px 8px;white-space:pre;display:none}
#stumm{position:fixed;left:0;right:0;top:40%;text-align:center;color:#fff;font:40px sans-serif;background:rgba(0,0,0,.6);padding:20px;display:none}</style></head>
<body><video id="v" autoplay playsinline></video><div id="info"></div><div id="stumm">Ton ist aus: bitte OK auf der Fernbedienung drücken</div>
<canvas id="c" width="496" height="40" style="display:none"></canvas>
<script>
const q = new URLSearchParams(location.search);
const v = document.getElementById('v'), info = document.getElementById('info'), stumm = document.getElementById('stumm');
if (q.get('info') === '1') info.style.display = 'block';
const typ = 'video/mp4; codecs="avc1.4d4028"', typTon = 'audio/mp4; codecs="mp4a.40.2"';
let letzte = '';
function melde(o) { o.jetzt = performance.now(); return fetch('/bericht', {method: 'POST', body: JSON.stringify(o)}).then(r => r.json()).catch(() => null); }
function fehler(wo, e) { melde({art: 'fehler', wo: wo, text: String(e && e.message || e)}); info.textContent = 'Fehler ' + wo + ': ' + e; }
window.onerror = (m) => fehler('seite', m);
v.addEventListener('error', () => fehler('video', v.error ? v.error.code + ' ' + v.error.message : '?'));
melde({art: 'faehig', ua: navigator.userAgent, mse: !!window.MediaSource, typ_ok: !!window.MediaSource && MediaSource.isTypeSupported(typ),
  ton_ok: !!window.MediaSource && MediaSource.isTypeSupported(typTon), w: innerWidth, h: innerHeight, dpr: devicePixelRatio});

// Bild und Ton kommen als zwei eigene Stroeme mit derselben Uhr (in einem gemeinsamen MP4 setzt ffmpeg die Bildzeiten ungleichmaessig)
const ms = new MediaSource();
v.src = URL.createObjectURL(ms);
async function leitung(adresse, art, name) {
  try {
    const sb = ms.addSourceBuffer(art);
    const schlange = [];
    const schieb = () => {
      if (sb.updating || !schlange.length) return;
      let n = 0; for (const c of schlange) n += c.length;
      const buf = new Uint8Array(n); let o = 0; for (const c of schlange) { buf.set(c, o); o += c.length; }
      schlange.length = 0;
      try { sb.appendBuffer(buf); } catch (e) { fehler('anhaengen ' + name, e); }
    };
    sb.addEventListener('updateend', () => {
      if (sb.buffered.length && v.currentTime - sb.buffered.start(0) > 20) { try { sb.remove(0, v.currentTime - 8); return; } catch (e) {} }
      schieb();
    });
    const r = await fetch(adresse);
    const leser = r.body.getReader();
    for (;;) { const {value, done} = await leser.read(); if (done) break; schlange.push(value); schieb(); }
    fehler('strom ' + name, 'zu Ende');
  } catch (e) { fehler('leitung ' + name, e); }
}
ms.addEventListener('sourceopen', () => {
  const id = Math.random().toString(36).slice(2);
  leitung('/strom.mp4?id=' + id, typ, 'Bild');
  leitung('/ton.mp4?id=' + id, typTon, 'Ton');
});

// mit Ton starten; erlaubt der Browser das nicht ohne Tastendruck, stumm starten und um OK bitten
let ohneTon = false;
const stummGewollt = q.get('stumm') === '1';      // ?stumm=1: nur das Bild, kein Ton und kein Hinweis
function laut() { if (stummGewollt) return; v.muted = false; v.play().then(() => { ohneTon = false; stumm.style.display = 'none'; }).catch(() => {}); }
v.muted = stummGewollt;
v.play().catch(() => { ohneTon = true; v.muted = true; if (!stummGewollt) stumm.style.display = 'block'; v.play().catch(e => fehler('abspielen', e)); });
addEventListener('keydown', laut); addEventListener('click', laut);

// Vorrat: einmal am Anfang auf 0,4 s stellen, danach nur noch bei grossem Rueckstand springen (kein Tempo aendern, der Ton soll sauber bleiben)
let vorrat = 0, spruenge = 0, gestellt = false;
const anfang = performance.now();
setInterval(() => {
  const b = v.buffered; if (!b.length) return;
  const ende = b.end(b.length - 1);
  vorrat = ende - v.currentTime;
  if (!gestellt && performance.now() - anfang > 2500) { gestellt = true; if (vorrat > 0.6) v.currentTime = ende - 0.4; return; }
  if (gestellt && vorrat > 1.5) { v.currentTime = ende - 0.4; spruenge++; }
}, 200);

// Bildnummer oben links lesen, nur fuenfmal je Sekunde (das Auslesen ist am Fernseher langsam)
const c = document.getElementById('c'), ctx = c.getContext('2d', {willReadFrequently: true});
let proben = [], lesefehler = 0;
function lies(zeit) {
  try {
    ctx.drawImage(v, 0, 0, 496, 40, 0, 0, 496, 40);
    const d = ctx.getImageData(0, 0, 496, 40).data;
    let n = 0, muster = '';
    for (let i = 0; i < 20; i++) {
      let s = 0;
      for (let y = 17; y < 23; y++) for (let x = 8 + i * 24 + 9; x < 8 + i * 24 + 15; x++) { const p = (y * 496 + x) * 4; s += d[p] + d[p + 1] + d[p + 2]; }
      const bit = s / 108 > 128 ? 1 : 0;
      if (i < 16) n = n * 2 + bit; else muster += bit;
    }
    if (muster !== '1010') { lesefehler++; return; }
    proben.push([n, zeit]);
  } catch (e) { lesefehler++; letzte = String(e); }
}
const mitRvfc = 'requestVideoFrameCallback' in HTMLVideoElement.prototype;
setInterval(() => {
  if (mitRvfc) v.requestVideoFrameCallback((jetzt, meta) => lies(meta && meta.expectedDisplayTime || jetzt));
  else if (v.readyState >= 2) lies(performance.now());
}, 200);
setInterval(async () => {
  const g = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
  const p = proben; proben = [];
  const a = await melde({art: 'mess', proben: p, vorrat: vorrat, gezeigt: g.totalVideoFrames || 0, verloren: g.droppedVideoFrames || 0,
    vw: v.videoWidth, vh: v.videoHeight, bereit: v.readyState, lesefehler: lesefehler, spruenge: spruenge, stumm: ohneTon || v.muted, letzte: letzte});
  if (a && a.text) info.textContent = a.text;
}, 2000);
</script></body></html>
"""


class Dienst(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a) -> None:
        pass

    def _kopf(self, code: int, typ: str, laenge: int | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", "no-store")
        if laenge is None:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Content-Length", str(laenge))
        self.end_headers()

    def do_GET(self) -> None:
        pfad = self.path.split("?")[0]
        if pfad == "/":
            daten = SEITE.encode("utf-8")
            self._kopf(200, "text/html; charset=utf-8", len(daten))
            self.wfile.write(daten)
            log(f"Seite geholt ({self.path})")
        elif pfad == "/strom.mp4":
            self.strom()
        elif pfad == "/ton.mp4":
            self.ton()
        else:
            self._kopf(404, "text/plain", 0)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(n) if n else b"{}"
        an = time.time()
        antwort = {"text": ""}
        try:
            antwort["text"] = bericht(json.loads(roh), an)
        except Exception as e:
            log(f"Bericht nicht lesbar: {type(e).__name__}: {e}")
        daten = json.dumps(antwort).encode("utf-8")
        self._kopf(200, "application/json", len(daten))
        self.wfile.write(daten)

    def _kennung(self) -> str:
        return (self.path.split("id=")[1].split("&")[0] if "id=" in self.path else "")[:32]

    def _leiten(self, lesen) -> None:
        self._kopf(200, "video/mp4")
        while True:
            daten = lesen(1 << 16)
            if not daten:
                break
            self.wfile.write(f"{len(daten):x}\r\n".encode() + daten + b"\r\n")
            self.wfile.flush()

    def strom(self) -> None:
        """Das Bild. Startet fuer diesen Zuschauer EINEN ffmpeg mit zwei Ausgaengen: Bild hier, Ton ueber /ton.mp4 mit derselben Kennung."""
        if not buehne.bereit.is_set():
            self._kopf(503, "text/plain", 0)
            return
        ton_rein_l, ton_rein_s = os.pipe()      # rohe Tonwerte hinein
        ton_raus_l, ton_raus_s = os.pipe()      # fertiger Tonstrom heraus
        stueckeln = ["-f", "mp4", "-movflags", "empty_moov+default_base_moof+frag_every_frame", "-flush_packets", "1"]
        enc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{B}x{H}", "-r", str(FPS), "-thread_queue_size", "64", "-i", "pipe:0",
             "-f", "s16le", "-ar", str(SR), "-ac", "1", "-probesize", "32", "-analyzeduration", "0", "-thread_queue_size", "64", "-i", f"pipe:{ton_rein_l}",
             "-map", "0:v", *KODIERER[buehne.a.kodierer], "-g", str(FPS), "-bf", "0", "-pix_fmt", "yuv420p", *stueckeln, "pipe:1",
             "-map", "1:a", "-c:a", "aac", "-ar", "48000", "-b:a", "128k", *stueckeln, f"pipe:{ton_raus_s}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, pass_fds=(ton_rein_l, ton_raus_s))
        os.close(ton_rein_l)
        os.close(ton_raus_s)
        ton_schlange: queue.Queue = queue.Queue()

        def ton_schreiber() -> None:  # eigener Thread: Bild und Ton duerfen sich beim Schreiben nie gegenseitig aufhalten
            try:
                while True:
                    daten = ton_schlange.get()
                    if daten is None:
                        break
                    os.write(ton_rein_s, daten)
            except OSError:
                pass

        threading.Thread(target=ton_schreiber, daemon=True).start()
        z = {"enc": enc, "ton": ton_schlange, "n": 0, "kennung": self._kennung(), "ton_raus": os.fdopen(ton_raus_l, "rb", buffering=0)}
        with buehne.klappe:
            alt = buehne.zuschauer
            buehne.zuschauer = z
        if alt is not None:
            alt["enc"].kill()
        log("Strom beginnt")
        try:
            self._leiten(enc.stdout.read1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with buehne.klappe:
                if buehne.zuschauer is z:
                    buehne.zuschauer = None
            enc.kill()
            ton_schlange.put(None)
            for zu in (lambda: os.close(ton_rein_s), z["ton_raus"].close):
                try:
                    zu()
                except OSError:
                    pass
            log(f"Strom endet nach {z['n']} Bildern")

    def ton(self) -> None:
        """Der Ton zum Strom mit derselben Kennung."""
        kennung = self._kennung()
        z = None
        for _ in range(100):                    # der Bild Strom mit dieser Kennung kommt gleichzeitig; kurz auf ihn warten
            with buehne.klappe:
                z = buehne.zuschauer
            if z is not None and z["kennung"] == kennung:
                break
            z = None
            time.sleep(0.05)
        if z is None:
            self._kopf(404, "text/plain", 0)
            return
        try:
            self._leiten(z["ton_raus"].read)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass


merk = {"gezeigt": 0, "verloren": 0, "zeit": 0.0}


def bericht(o: dict, an: float) -> str:
    art = o.get("art")
    if art == "faehig":
        log(f"BROWSER: {json.dumps({k: v for k, v in o.items() if k not in ('art', 'jetzt')}, ensure_ascii=False)}")
        merk.update(gezeigt=0, verloren=0, zeit=an)
        return "verbunden"
    if art == "fehler":
        log(f"FEHLER: {o.get('wo')}: {o.get('text')}")
        return "Fehler gemeldet"
    if art != "mess":
        return ""
    jetzt = float(o.get("jetzt") or 0.0)
    lat = []
    for n, t in o.get("proben") or []:
        ab = gesendet[int(n) & 0xFFFF]
        if ab:
            lat.append((an - (jetzt - float(t)) / 1000.0 - ab) * 1000.0)
    gez, verl = int(o.get("gezeigt") or 0), int(o.get("verloren") or 0)
    dauer = max(0.001, an - merk["zeit"])
    rate, weg = (gez - merk["gezeigt"]) / dauer, verl - merk["verloren"]
    merk.update(gezeigt=gez, verloren=verl, zeit=an)
    if lat:
        text = f"Verzoegerung {sum(lat) / len(lat):.0f} ms ({min(lat):.0f} bis {max(lat):.0f})"
    else:
        text = f"keine Marke gelesen (bereit {o.get('bereit')}, {o.get('letzte')})"
    text += (f", {rate:.1f} Bilder/s, verloren {weg} (gesamt {verl} von {gez}), Vorrat {float(o.get('vorrat') or 0) * 1000:.0f} ms, "
             f"Spruenge {o.get('spruenge')}, Ton {'AUS' if o.get('stumm') else 'an'}, Bild {o.get('vw')}x{o.get('vh')}")
    log("MESS: " + text)
    return text


def main() -> None:
    global buehne
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=str(ORT.parent / "eingabe" / "tv_aermel.mp4"))
    ap.add_argument("--ton", default=str(ORT.parent / "eingabe" / "leyla.wav"))
    ap.add_argument("--x", type=int, default=1278)
    ap.add_argument("--y", type=int, default=20)
    ap.add_argument("--punkte", default="1,2,6,12,14,17,19,20")
    ap.add_argument("--staerke", type=float, default=1.7)
    ap.add_argument("--schwelle", type=float, default=0.02)
    ap.add_argument("--pause", type=float, default=6.0, help="Sekunden Ruhe zwischen zwei Saetzen")
    ap.add_argument("--marke", type=int, default=1, help="1 = Messmarke oben links ins Bild (fuer die Verzoegerung)")
    ap.add_argument("--kodierer", default="x264", choices=sorted(KODIERER))
    ap.add_argument("--attrappe", action="store_true")
    a = ap.parse_args()
    ENDE.unlink(missing_ok=True)
    SPRICH.unlink(missing_ok=True)
    buehne = Buehne(a)
    log(f"Vorfuehrung startet ({'Attrappe' if a.attrappe else 'mit Modellen'}); Clip {Path(a.clip).name}, Satz {Path(a.ton).name}")
    threading.Thread(target=buehne.rechner, daemon=True).start()
    threading.Thread(target=buehne.sender, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Dienst)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while not ENDE.exists():
        time.sleep(1)
    ENDE.unlink(missing_ok=True)
    log("BEENDET")
    server.shutdown()


if __name__ == "__main__":
    main()
