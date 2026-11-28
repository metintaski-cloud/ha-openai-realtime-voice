# Leyla Mund Dienst (28.11.2026): Leyla spricht am Fernseher live und synchron, ihre Stimme kommt aus der Voice PE.
#
# Laeuft im Behaelter auf Metins PC. Der Clip laeuft als Schleife in Full HD; trifft Leylas Stimme vom Add on ein,
# werden Mund und Kinn live gerechnet (mundkern.py) und in den laufenden Strom gesetzt.
#   Port 8090 (HTTP)   /            Seite fuer den Fernseher (Vollbild Video)
#                      /strom.mp4   der Strom, nur Bild (H.264, fragmentiertes MP4)
#                      /bericht     die Seite meldet, welches Bild sie wann gezeigt hat (daraus die Verzoegerung)
#                      /stand       Zustand als JSON
#   Port 8091 (TCP)    das Add on: Rahmen = 1 Byte Art + 4 Byte Laenge (big endian) + Inhalt
#                      S {"in_ms": N}  eine Rede beginnt; ihr erster Ton erklingt an der Voice in N ms
#                      A Ton           16 Bit mono 24 kHz, so wie er von GPT Live kommt
#                      E               die Rede ist zu Ende
#                      X               Abbruch (Leyla wurde unterbrochen): sofort zurueck zum Clip
#                      zurueck kommt jede Sekunde eine JSON Zeile {"bereit", "zuschauer", "strom_ms"}
# Zeitplan: beim S steht die Buehne bei Bild A. Das Bild zu Ton Bild j erscheint im Strom bei A + V + j mit
# V = (in_ms - Verzoegerung des Stroms) / 40 ms, mindestens MIN_V (so lange braucht das Rechnen). So trifft das
# Bild am Fernseher ein, wenn der Ton an der Voice erklingt.
# Datei avtr/sprich.txt: der Testsatz wird wie vom Add on eingespielt. avtr/munddienst_ende.txt: beenden.
# --attrappe: ohne Modelle (helles Feld statt Mund), um den ganzen Weg in jeder Umgebung zu pruefen.
from __future__ import annotations

import argparse
import json
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

B, H, FPS, SR = 1920, 1080, 25, 16_000
HTTP_PORT, TON_PORT = 8090, 8091
MIN_V = 18                     # Bilder: Stueck 200 ms + Vorschau 200 ms + Rechnen + 2 Bilder Maske
RX, RY, RB, RH = 640, 10, 640, 360   # der Kopf Ausschnitt im Full HD Bild (4K: 1278,20 und 1280 x 720; 1 Punkt Rand links)
ORT = Path(__file__).resolve().parent
LOG = ORT / "munddienst_log.txt"
ENDE = ORT / "munddienst_ende.txt"
SPRICH = ORT / "sprich.txt"
KODIERER = {  # x264 im Prozessor (auf Metins PC geprueft), nvenc auf der Grafikkarte, schnell nur fuer schwache Rechner
    "x264": ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "main", "-level", "4.0", "-crf", "20", "-maxrate", "12M", "-bufsize", "6M"],
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-profile:v", "main", "-level", "4.0", "-rc", "vbr", "-cq", "23", "-maxrate", "12M", "-bufsize", "6M"],
    "schnell": ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "23"],
}

sperre = threading.Lock()


def log(text: str) -> None:
    zeile = time.strftime("%H:%M:%S ") + text
    print(zeile, flush=True)
    with sperre, LOG.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")


def lade_ton(pfad: str, rate: int) -> np.ndarray:
    roh = subprocess.run(["ffmpeg", "-v", "error", "-i", pfad, "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(roh, dtype="<i2").copy()


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


def auf_16k(pcm24: np.ndarray) -> np.ndarray:
    """24 kHz int16 -> 16 kHz float (3 Werte werden 2). Fuer das Mund Modell reicht das geradlinige Umrechnen."""
    x = pcm24.astype(np.float32) / 32768.0
    n = len(x) * 2 // 3
    stellen = np.arange(n, dtype=np.float32) * 1.5
    lo = np.minimum(stellen.astype(np.int64), len(x) - 1)
    hi = np.minimum(lo + 1, len(x) - 1)
    teil = stellen - lo
    return x[lo] * (1.0 - teil) + x[hi] * teil


class AttrappeRede:
    """Ohne Modelle: statt des Munds ein helles Feld, dessen Groesse der Lautstaerke folgt. Nur zum Pruefen des Wegs."""

    def __init__(self, kern, versatz):
        self.k, self.versatz = kern, versatz
        self.ton = np.zeros(0, dtype=np.float32)
        self.zu = False
        self.zeiten: list[float] = []

    def fuettern(self, st):
        self.ton = np.concatenate([self.ton, st.astype(np.float32)])

    def ende(self):
        self.zu = True

    @property
    def stuecke(self):
        return max(1, (len(self.ton) + self.k.schritt - 1) // self.k.schritt)

    @property
    def n(self):
        return self.stuecke * self.k.CS

    def kann(self, s):
        return len(self.ton) >= s * self.k.schritt + self.k.fenster or (self.zu and s < self.stuecke)

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
    CS, voraus, schritt, fenster = 5, 10, 3200, 6480

    def __init__(self, clip: np.ndarray):
        self.clip, self.N = clip, len(clip)

    def neue_rede(self, versatz, ton=None):
        return AttrappeRede(self, versatz)


class Buehne:
    """Haelt den Takt: ein Bild alle 40 ms. Drei Threads teilen sich diesen Stand: Rechnen, Senden, Ton Eingang."""

    def __init__(self, a):
        self.a = a
        self.clip = None
        self.kern = None
        self.bereit = threading.Event()
        self.pos = 0                 # Bild Nummer der Buehne, laeuft immer weiter
        self.rede = None             # siehe beginne()
        self.zuschauer = None        # {"enc", "n"}
        self.klappe = threading.Lock()
        self.gesendet = [0.0] * 65536   # Bild Nummer des Zuschauers -> Zeit, als es in den Kodierer ging
        self.strom_ms = float(a.strom_ms)   # gemessene Verzoegerung vom Abschicken bis zum Zeigen
        self.gemessen = 0.0          # wann zuletzt gemessen wurde
        self.reden = 0

    # ---------------------------------------------------------------- Eingang: was das Add on (oder der Test) schickt
    def beginne(self, in_ms: float) -> None:
        with self.klappe:
            v = max(MIN_V, int(round((in_ms - self.strom_ms) / 40.0)))
            self.rede = {"A": self.pos, "V": v, "obj": None, "puffer": [], "ende": False, "fertig": {}, "s": 0, "zu": False,
                         "gezeigt": 0, "in_ms": in_ms, "knapp": v == MIN_V and in_ms - self.strom_ms < MIN_V * 40 - 20,
                         "letzter": time.time()}
            self.reden += 1

    def ton(self, pcm24: np.ndarray) -> None:
        with self.klappe:
            if self.rede is not None and not self.rede["ende"]:
                self.rede["puffer"].append(auf_16k(pcm24))
                self.rede["letzter"] = time.time()

    def beende(self) -> None:
        with self.klappe:
            if self.rede is not None:
                self.rede["ende"] = True

    def brich_ab(self) -> None:
        with self.klappe:
            if self.rede is not None:
                log(f"REDE abgebrochen nach {self.rede['gezeigt']} Bildern")
            self.rede = None

    # ---------------------------------------------------------------- Rechnen (einziger Thread mit der Grafikkarte)
    def rechner(self) -> None:
        try:
            self._rechner()
        except Exception:  # sonst stirbt der Thread still und niemand erfaehrt, warum nichts kommt
            import traceback
            log("FEHLER im Rechner: " + traceback.format_exc().replace("\n", " | "))

    def _rechner(self) -> None:
        a = self.a
        self.clip = lade_clip(a.clip, a.x)
        log(f"Clip in Full HD geladen: {len(self.clip)} Bilder")
        if a.attrappe:
            self.kern = Attrappe(self.clip)
        else:
            from mundkern import MundKern
            self.kern = MundKern(a.clip, a.x, a.y, a.punkte, a.staerke, a.schwelle, melde=log)
        assert self.kern.N == len(self.clip), f"Clip Laengen verschieden: {self.kern.N} und {len(self.clip)}"
        self.bereit.set()
        log(f"BEREIT: Seite und Strom auf Port {HTTP_PORT}, Ton vom Add on auf Port {TON_PORT}. Dieses Fenster offen lassen.")
        k = self.kern
        while True:
            with self.klappe:
                r = self.rede
                neu = r["puffer"][:] if r is not None else []
                if r is not None:
                    r["puffer"].clear()
                    if not r["ende"] and time.time() - r["letzter"] > 1.5:   # das Ende kam nie an: nicht ewig offen bleiben
                        r["ende"] = True
                    ende = r["ende"]
            if r is None:
                time.sleep(0.004)
                continue
            if r["obj"] is None:
                r["obj"] = k.neue_rede(r["A"] + r["V"])
            obj = r["obj"]
            for st in neu:
                obj.fuettern(st)
            if ende and not obj.zu:
                obj.ende()
            if obj.kann(r["s"]):
                aus = obj.rechne_stueck(r["s"])
                with self.klappe:
                    r["fertig"].update(aus)
                    r["s"] += 1
            elif obj.zu and r["s"] >= obj.stuecke and not r["zu"]:
                aus = obj.schluss()
                with self.klappe:
                    r["fertig"].update(aus)
                    r["zu"] = True
            else:
                time.sleep(0.003)

    # ---------------------------------------------------------------- Senden (ein Bild alle 40 ms)
    def sender(self) -> None:
        self.bereit.wait()
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
            reg = None
            if r is not None:
                j = p - r["A"] - r["V"]
                obj = r["obj"]
                if j >= 0:
                    with self.klappe:
                        reg = r["fertig"].pop(j, None)
                    if reg is not None:
                        r["gezeigt"] += 1
                    elif r["zu"] and obj is not None and j >= obj.n:
                        zt = np.array(obj.zeiten or [0.0]) * 1000
                        log(f"REDE fertig: {r['gezeigt']} von {obj.n} Bildern mit live gerechnetem Mund (in_ms {r['in_ms']:.0f}, Vorlauf {r['V']} Bilder"
                            f"{', ZU KNAPP' if r['knapp'] else ''}); Rechnen je Stueck Mittel {zt.mean():.0f} ms, Spitze {zt.max():.0f} ms")
                        with self.klappe:
                            if self.rede is r:
                                self.rede = None
            if z is not None:
                bild = self.clip[p % len(self.clip)]
                if reg is not None:
                    bild = bild.copy()
                    bild[RY:RY + RH, RX:RX + RB] = reg
                try:
                    self.gesendet[z["n"] & 0xFFFF] = time.time()
                    z["enc"].stdin.write(bild.tobytes())
                    z["enc"].stdin.flush()
                    z["n"] += 1
                except (BrokenPipeError, OSError):
                    with self.klappe:
                        if self.zuschauer is z:
                            self.zuschauer = None
            self.pos = p + 1

    # ---------------------------------------------------------------- Ton Eingang vom Add on (TCP)
    def stand(self) -> dict:
        frisch = time.time() - self.gemessen < 5.0
        return {"bereit": self.bereit.is_set(), "zuschauer": self.zuschauer is not None and frisch,
                "strom_ms": round(self.strom_ms), "reden": self.reden}

    def ton_dienst(self) -> None:
        self.bereit.wait()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", TON_PORT))
        srv.listen(2)
        while True:
            verb, wer = srv.accept()
            threading.Thread(target=self._ton_leitung, args=(verb, wer), daemon=True).start()

    def _ton_leitung(self, verb: socket.socket, wer) -> None:
        log(f"Add on verbunden ({wer[0]})")
        verb.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        aus = threading.Event()

        def melder() -> None:
            while not aus.is_set():
                try:
                    verb.sendall((json.dumps(self.stand()) + "\n").encode())
                except OSError:
                    break
                aus.wait(1.0)

        threading.Thread(target=melder, daemon=True).start()

        def lies(n: int) -> bytes:
            teile = b""
            while len(teile) < n:
                d = verb.recv(n - len(teile))
                if not d:
                    raise ConnectionError
                teile += d
            return teile

        try:
            while True:
                art, laenge = struct.unpack(">cI", lies(5))
                if laenge > 4_000_000:
                    raise ConnectionError
                inhalt = lies(laenge) if laenge else b""
                if art == b"S":
                    self.beginne(float(json.loads(inhalt or b"{}").get("in_ms", 1300)))
                elif art == b"A":
                    self.ton(np.frombuffer(inhalt[:len(inhalt) // 2 * 2], dtype="<i2"))
                elif art == b"E":
                    self.beende()
                elif art == b"X":
                    self.brich_ab()
        except (ConnectionError, OSError, struct.error, ValueError):
            pass
        finally:
            aus.set()
            self.brich_ab()                  # reisst die Leitung mitten in einer Rede ab, bleibt kein offener Mund stehen
            verb.close()
            log("Add on getrennt")

    # ---------------------------------------------------------------- Test: der Satz aus der Datei, wie vom Add on geschickt
    def probe_sprecher(self) -> None:
        self.bereit.wait()
        satz = lade_ton(self.a.ton, 24000)
        naechste = time.time() + self.a.pause if self.a.vorfuehrung else None
        while True:
            time.sleep(0.2)
            faellig = SPRICH.exists() or (naechste is not None and time.time() >= naechste and self.zuschauer is not None)
            if not faellig or self.rede is not None:
                continue
            SPRICH.unlink(missing_ok=True)
            self.beginne(self.a.probe_in_ms)
            t0 = time.perf_counter()
            for i in range(0, len(satz), 960):                    # 40 ms Stuecke im echten Takt
                warte = t0 + i / 24000 - time.perf_counter()
                if warte > 0:
                    time.sleep(warte)
                self.ton(satz[i:i + 960])
            self.beende()
            if naechste is not None:
                naechste = time.time() + self.a.pause


buehne: Buehne | None = None

SEITE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Leyla live</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;background:#000;overflow:hidden;cursor:none}video{width:100vw;height:100vh;object-fit:contain;background:#000}
#info{position:fixed;left:12px;bottom:10px;color:#7f7;font:18px monospace;background:rgba(0,0,0,.55);padding:4px 8px;white-space:pre;display:none}</style></head>
<body><video id="v" muted autoplay playsinline></video><div id="info"></div>
<script>
const q = new URLSearchParams(location.search);
const v = document.getElementById('v'), info = document.getElementById('info');
if (q.get('info') === '1') info.style.display = 'block';
const zurueck = q.get('zurueck') || '';      // dorthin, wenn der Strom abreisst (die normale Fernseher Seite)
const ZIEL = 400;                             // so viele ms soll das Bild hinter dem Abschicken liegen; der Dienst rechnet damit
const typ = 'video/mp4; codecs="avc1.4d4028"';
function melde(o) { o.jetzt = performance.now(); return fetch('/bericht', {method: 'POST', body: JSON.stringify(o)}).then(r => r.json()).catch(() => null); }
let weg = false;
function heim(grund) {
  if (weg) return; weg = true;
  melde({art: 'fehler', wo: 'heim', text: String(grund)});
  if (zurueck) setTimeout(() => location.replace(zurueck), 3000); else setTimeout(() => location.reload(), 5000);
}
function fehler(wo, e) { melde({art: 'fehler', wo: wo, text: String(e && e.message || e)}); info.textContent = 'Fehler ' + wo + ': ' + e; heim(wo); }
window.onerror = (m) => fehler('seite', m);
v.addEventListener('error', () => fehler('video', v.error ? v.error.code + ' ' + v.error.message : '?'));
if (!window.MediaSource || !MediaSource.isTypeSupported(typ) || !('requestVideoFrameCallback' in HTMLVideoElement.prototype)) fehler('browser', 'kann den Strom nicht zeigen');
melde({art: 'faehig', ua: navigator.userAgent, w: innerWidth, h: innerHeight, dpr: devicePixelRatio});

const ms = new MediaSource();
v.src = URL.createObjectURL(ms);
ms.addEventListener('sourceopen', async () => {
  try {
    const sb = ms.addSourceBuffer(typ);
    const schlange = [];
    const schieb = () => {
      if (sb.updating || !schlange.length) return;
      let n = 0; for (const c of schlange) n += c.length;
      const buf = new Uint8Array(n); let o = 0; for (const c of schlange) { buf.set(c, o); o += c.length; }
      schlange.length = 0;
      try { sb.appendBuffer(buf); } catch (e) { fehler('anhaengen', e); }
    };
    sb.addEventListener('updateend', () => {
      if (sb.buffered.length && v.currentTime - sb.buffered.start(0) > 20) { try { sb.remove(0, v.currentTime - 8); return; } catch (e) {} }
      schieb();
    });
    const r = await fetch('/strom.mp4');
    if (!r.ok) throw new Error('Strom ' + r.status);
    const leser = r.body.getReader();
    for (;;) { const {value, done} = await leser.read(); if (done) break; schlange.push(value); schieb(); }
    fehler('strom', 'zu Ende');
  } catch (e) { fehler('mse', e); }
});
v.play().catch(e => fehler('abspielen', e));

// Welches Bild wird wann gezeigt? mediaTime ist die Bildnummer / 25; der Dienst weiss, wann er dieses Bild abgeschickt hat.
let proben = [], letzteZeit = performance.now(), letzteMedia = -1;
const bild = (jetzt, meta) => {
  if (meta.mediaTime !== letzteMedia) { letzteMedia = meta.mediaTime; letzteZeit = performance.now(); if (proben.length < 60) proben.push([meta.mediaTime, meta.expectedDisplayTime || jetzt]); }
  v.requestVideoFrameCallback(bild);
};
v.requestVideoFrameCallback(bild);
// Die Verzoegerung beim Ziel halten: nur das Tempo des Bilds leicht aendern (es gibt keinen Ton im Strom)
let spruenge = 0;
setInterval(async () => {
  const g = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
  const b = v.buffered, vorrat = b.length ? b.end(b.length - 1) - v.currentTime : 0;
  const p = proben; proben = [];
  const a = await melde({art: 'mess', proben: p, vorrat: vorrat, gezeigt: g.totalVideoFrames || 0, verloren: g.droppedVideoFrames || 0, tempo: v.playbackRate, spruenge: spruenge});
  if (a && a.text) info.textContent = a.text;
  if (a && typeof a.ms === 'number') {
    if (a.ms > ZIEL + 900 && b.length) { v.currentTime = b.end(b.length - 1) - 0.25; spruenge++; }
    else if (a.ms > ZIEL + 60) v.playbackRate = 1.06;
    else if (a.ms < ZIEL - 60) v.playbackRate = 0.95;
    else v.playbackRate = 1.0;
  }
  if (performance.now() - letzteZeit > 8000) heim('das Bild steht');
}, 1000);
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
        self.send_header("Access-Control-Allow-Origin", "*")
        if laenge is None:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Content-Length", str(laenge))
        self.end_headers()

    def _json(self, o: dict) -> None:
        daten = json.dumps(o).encode("utf-8")
        self._kopf(200, "application/json", len(daten))
        self.wfile.write(daten)

    def do_GET(self) -> None:
        pfad = self.path.split("?")[0]
        if pfad == "/":
            daten = SEITE.encode("utf-8")
            self._kopf(200, "text/html; charset=utf-8", len(daten))
            self.wfile.write(daten)
            log("Seite geholt")
        elif pfad == "/strom.mp4":
            self.strom()
        elif pfad == "/stand":
            self._json(buehne.stand())
        else:
            self._kopf(404, "text/plain", 0)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(n) if n else b"{}"
        an = time.time()
        antwort: dict = {"text": ""}
        try:
            antwort = bericht(json.loads(roh), an)
        except Exception as e:
            log(f"Bericht nicht lesbar: {type(e).__name__}: {e}")
        self._json(antwort)

    def strom(self) -> None:
        if not buehne.bereit.is_set():
            self._kopf(503, "text/plain", 0)
            return
        enc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{B}x{H}", "-r", str(FPS), "-i", "pipe:0",
             *KODIERER[buehne.a.kodierer], "-g", str(FPS), "-bf", "0", "-pix_fmt", "yuv420p",
             "-f", "mp4", "-movflags", "empty_moov+default_base_moof+frag_every_frame", "-flush_packets", "1", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        z = {"enc": enc, "n": 0}
        with buehne.klappe:
            alt = buehne.zuschauer
            buehne.zuschauer = z
            buehne.gemessen = time.time()
        if alt is not None:
            alt["enc"].kill()
        log("Strom beginnt")
        try:
            self._kopf(200, "video/mp4")
            while True:
                daten = enc.stdout.read1(1 << 16)
                if not daten:
                    break
                self.wfile.write(f"{len(daten):x}\r\n".encode() + daten + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with buehne.klappe:
                if buehne.zuschauer is z:
                    buehne.zuschauer = None
            enc.kill()
            log(f"Strom endet nach {z['n']} Bildern")


merk = {"gezeigt": 0, "verloren": 0, "zeit": 0.0, "zeilen": 0}


def bericht(o: dict, an: float) -> dict:
    art = o.get("art")
    if art == "faehig":
        log(f"BROWSER: {json.dumps({k: v for k, v in o.items() if k not in ('art', 'jetzt')}, ensure_ascii=False)}")
        merk.update(gezeigt=0, verloren=0, zeit=an, zeilen=0)
        return {"text": "verbunden"}
    if art == "fehler":
        log(f"SEITE: {o.get('wo')}: {o.get('text')}")
        return {"text": "gemeldet"}
    if art != "mess":
        return {"text": ""}
    jetzt = float(o.get("jetzt") or 0.0)
    z = buehne.zuschauer
    lat = []
    for media, t in o.get("proben") or []:
        n = int(round(float(media) * FPS))
        ab = buehne.gesendet[n & 0xFFFF]
        if ab and z is not None and n < z["n"]:
            lat.append((an - (jetzt - float(t)) / 1000.0 - ab) * 1000.0)
    gez, verl = int(o.get("gezeigt") or 0), int(o.get("verloren") or 0)
    rate, weg = (gez - merk["gezeigt"]) / max(0.001, an - merk["zeit"]), verl - merk["verloren"]
    merk.update(gezeigt=gez, verloren=verl, zeit=an, zeilen=merk["zeilen"] + 1)
    aus: dict = {}
    if lat:
        mitte = sorted(lat)[len(lat) // 2]
        buehne.strom_ms = 0.7 * buehne.strom_ms + 0.3 * mitte        # geglaettet: daraus wird der Vorlauf der naechsten Rede
        buehne.gemessen = an
        aus["ms"] = mitte
        text = f"Verzoegerung {mitte:.0f} ms ({min(lat):.0f} bis {max(lat):.0f}), geglaettet {buehne.strom_ms:.0f}"
    else:
        text = "keine Messung"
    text += f", {rate:.1f} Bilder/s, verloren {weg} (gesamt {verl} von {gez}), Vorrat {float(o.get('vorrat') or 0) * 1000:.0f} ms, Tempo {o.get('tempo')}, Spruenge {o.get('spruenge')}"
    if merk["zeilen"] <= 20 or merk["zeilen"] % 10 == 0 or weg > 3:      # am Anfang jede Sekunde, dann alle zehn
        log("MESS: " + text)
    aus["text"] = text
    return aus


def main() -> None:
    global buehne
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=str(ORT.parent / "eingabe" / "tv_aermel.mp4"))
    ap.add_argument("--ton", default=str(ORT.parent / "eingabe" / "leyla.wav"), help="Testsatz fuer sprich.txt und --vorfuehrung")
    ap.add_argument("--x", type=int, default=1278)
    ap.add_argument("--y", type=int, default=20)
    ap.add_argument("--punkte", default="1,2,6,12,14,17,19,20")
    ap.add_argument("--staerke", type=float, default=1.7)
    ap.add_argument("--schwelle", type=float, default=0.02)
    ap.add_argument("--kodierer", default="x264", choices=sorted(KODIERER))
    ap.add_argument("--strom-ms", dest="strom_ms", type=float, default=400.0, help="angenommene Verzoegerung des Stroms, bis gemessen ist")
    ap.add_argument("--vorfuehrung", action="store_true", help="den Testsatz von selbst immer wieder sprechen")
    ap.add_argument("--pause", type=float, default=6.0)
    ap.add_argument("--probe-in-ms", dest="probe_in_ms", type=float, default=1300.0)
    ap.add_argument("--attrappe", action="store_true")
    a = ap.parse_args()
    ENDE.unlink(missing_ok=True)
    SPRICH.unlink(missing_ok=True)
    buehne = Buehne(a)
    log(f"Mund Dienst startet ({'Attrappe' if a.attrappe else 'mit Modellen'}); Clip {Path(a.clip).name}")
    for ziel in (buehne.rechner, buehne.sender, buehne.ton_dienst, buehne.probe_sprecher):
        threading.Thread(target=ziel, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Dienst)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while not ENDE.exists():
        time.sleep(1)
    ENDE.unlink(missing_ok=True)
    log("BEENDET")
    server.shutdown()


if __name__ == "__main__":
    main()
