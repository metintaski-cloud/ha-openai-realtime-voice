# Leyla Strom Test (28.11.2026, Stufe 2 Teil 2): zeigt der Browser am Fernseher einen laufenden Videostrom vom PC?
#
# Dieser kleine Dienst laeuft im Behaelter auf Metins PC (Port 8090) und tut drei Dinge:
#   /            die Testseite (ein Video im Vollbild und ein paar Zeilen Messung)
#   /strom.mp4   ein endloser Videostrom: das fertig gerechnete Leyla Video in Full HD, 25 Bilder je Sekunde,
#                H.264 in kleinen Stuecken (fragmentiertes MP4), jedes Bild traegt oben links seine Nummer
#                als Reihe heller und dunkler Felder
#   /bericht     die Seite meldet, was der Browser kann und welches Bild sie wann gezeigt hat
# Aus "wann abgeschickt" und "wann gezeigt" ergibt sich die Verzoegerung der Uebertragung; dazu, ob Bilder fehlen.
# Es wird nichts gerechnet (kein Modell, keine Grafikkarte) und nichts gespeichert ausser avtr/strom_log.txt.
# Beenden: Fenster schliessen oder die Datei avtr/strom_ende.txt anlegen.
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

B, H, FPS = 1920, 1080, 25
PORT = 8090
FELD, RAND, FELDER = 24, 8, 20          # 16 Felder Bildnummer, 4 Felder festes Muster 1 0 1 0
BILD = B * H * 3 // 2                   # yuv420p
ORT = Path(__file__).resolve().parent
LOG = ORT / "strom_log.txt"
ENDE = ORT / "strom_ende.txt"
KLEIN = Path("/dev/shm/leyla_strom_1080.mp4") if Path("/dev/shm").is_dir() else ORT / "strom_1080.mp4"

gesendet = [0.0] * 65536                # Bildnummer -> Zeit, als das Bild in den Kodierer ging
sperre = threading.Lock()


def log(text: str) -> None:
    zeile = time.strftime("%H:%M:%S ") + text
    print(zeile, flush=True)
    with sperre, LOG.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")


def quelle_finden() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    kandidaten = sorted((ORT.parent / "ergebnis").glob("leyla_live_*_4k.mp4"), key=lambda p: p.stat().st_mtime)
    if not kandidaten:
        raise SystemExit("Kein Video ergebnis/leyla_live_*_4k.mp4 gefunden")
    return kandidaten[-1]


def vorbereiten() -> None:
    q = quelle_finden()
    log(f"Quelle {q.name}: wird einmal auf {B} x {H} verkleinert")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(q), "-an", "-vf", f"fps={FPS},scale={B}:{H}:flags=lanczos",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-g", "25", "-pix_fmt", "yuv420p", str(KLEIN)], check=True)


def nummer_setzen(bild: bytearray, n: int) -> None:
    bits = [(n >> (15 - i)) & 1 for i in range(16)] + [1, 0, 1, 0]
    for i, bit in enumerate(bits):
        wert = bytes([235 if bit else 16]) * FELD
        x = RAND + i * FELD
        for y in range(RAND, RAND + FELD):
            o = y * B + x
            bild[o:o + FELD] = wert


SEITE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Leyla Strom Test</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;background:#000;overflow:hidden}video{width:100vw;height:100vh;object-fit:contain;background:#000}
#info{position:fixed;left:12px;bottom:10px;color:#7f7;font:18px monospace;background:rgba(0,0,0,.55);padding:4px 8px;white-space:pre}</style></head>
<body><video id="v" muted autoplay playsinline></video><div id="info">Leyla Strom Test startet ...</div><canvas id="c" width="496" height="40" style="display:none"></canvas>
<script>
const q = new URLSearchParams(location.search);
const weg = q.get('weg') || 'mse';
const jagd = q.get('jagd') !== '0';
const v = document.getElementById('v'), info = document.getElementById('info');
const typ = 'video/mp4; codecs="avc1.4d4028"';
let letzte = '';
function melde(o) {
  o.jetzt = performance.now();
  return fetch('/bericht', {method: 'POST', body: JSON.stringify(o)}).then(r => r.json()).catch(() => null);
}
function fehler(wo, e) { melde({art: 'fehler', wo: wo, text: String(e && e.message || e)}); info.textContent = 'Fehler ' + wo + ': ' + e; }
window.onerror = (m) => fehler('seite', m);
v.addEventListener('error', () => fehler('video', v.error ? v.error.code + ' ' + v.error.message : '?'));
melde({art: 'faehig', ua: navigator.userAgent, mse: !!window.MediaSource, typ_ok: !!window.MediaSource && MediaSource.isTypeSupported(typ),
  rtc: !!window.RTCPeerConnection, rvfc: 'requestVideoFrameCallback' in HTMLVideoElement.prototype, webcodecs: 'VideoDecoder' in window,
  w: innerWidth, h: innerHeight, dpr: devicePixelRatio, sw: screen.width, sh: screen.height, weg: weg, jagd: jagd});

let sb = null;
if (weg === 'mse' && window.MediaSource) {
  const ms = new MediaSource();
  v.src = URL.createObjectURL(ms);
  ms.addEventListener('sourceopen', async () => {
    try {
      sb = ms.addSourceBuffer(typ);
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
      const leser = r.body.getReader();
      for (;;) { const {value, done} = await leser.read(); if (done) break; schlange.push(value); schieb(); }
      fehler('strom', 'zu Ende');
    } catch (e) { fehler('mse', e); }
  });
} else {
  v.src = '/strom.mp4';
}
v.play().catch(e => fehler('abspielen', e));

// dem Ende des Stroms auf den Fersen bleiben: wenig Vorrat heisst wenig Verzoegerung
let vorrat = 0, spruenge = 0;
setInterval(() => {
  const b = v.buffered; if (!b.length) return;
  vorrat = b.end(b.length - 1) - v.currentTime;
  if (!jagd) return;
  if (vorrat > 1.5) { v.currentTime = b.end(b.length - 1) - 0.1; spruenge++; }
  else if (vorrat > 0.25) v.playbackRate = 1.1;
  else if (vorrat < 0.12) v.playbackRate = 1.0;
}, 200);

// Bildnummer oben links lesen
const c = document.getElementById('c'), ctx = c.getContext('2d', {willReadFrequently: true});
let proben = [], zuletzt = -1, lesefehler = 0;
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
    if (n !== zuletzt) { zuletzt = n; proben.push([n, zeit]); }
  } catch (e) { lesefehler++; letzte = String(e); }
}
if ('requestVideoFrameCallback' in HTMLVideoElement.prototype) {
  const f = (jetzt, meta) => { lies(meta && meta.expectedDisplayTime || jetzt); v.requestVideoFrameCallback(f); };
  v.requestVideoFrameCallback(f);
} else {
  const f = (jetzt) => { if (v.readyState >= 2) lies(jetzt); requestAnimationFrame(f); };
  requestAnimationFrame(f);
}
setInterval(async () => {
  const g = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
  const p = proben; proben = [];
  const a = await melde({art: 'mess', proben: p, vorrat: vorrat, gezeigt: g.totalVideoFrames || 0, verloren: g.droppedVideoFrames || 0,
    ct: v.currentTime, rate: v.playbackRate, vw: v.videoWidth, vh: v.videoHeight, bereit: v.readyState, lesefehler: lesefehler, spruenge: spruenge, letzte: letzte});
  if (a && a.text) info.textContent = a.text;
}, 1000);
</script></body></html>
"""


class Dienst(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a) -> None:  # die eigenen Zeilen reichen
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
            log(f"Seite geholt von {self.client_address[0]} ({self.path})")
        elif pfad == "/strom.mp4":
            self.strom()
        else:
            self._kopf(404, "text/plain", 0)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(n) if n else b"{}"
        an = time.time()
        antwort = {"text": ""}
        try:
            o = json.loads(roh)
            antwort["text"] = bericht(o, an, self.client_address[0])
        except Exception as e:  # ein kaputter Bericht darf den Dienst nicht stoppen
            log(f"Bericht nicht lesbar: {type(e).__name__}: {e}")
        daten = json.dumps(antwort).encode("utf-8")
        self._kopf(200, "application/json", len(daten))
        self.wfile.write(daten)

    def strom(self) -> None:
        log(f"Strom beginnt fuer {self.client_address[0]}")
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(KLEIN), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                               stdout=subprocess.PIPE)
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{B}x{H}", "-r", str(FPS), "-i", "-",
                                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "main", "-level", "4.0",
                                "-g", str(FPS), "-bf", "0", "-crf", "20", "-maxrate", "12M", "-bufsize", "6M", "-pix_fmt", "yuv420p",
                                "-f", "mp4", "-movflags", "empty_moov+default_base_moof+frag_every_frame", "-flush_packets", "1", "-"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        stopp = threading.Event()

        def fuettern() -> None:
            n = 0
            t0 = time.perf_counter()
            try:
                while not stopp.is_set():
                    roh = dec.stdout.read(BILD)
                    if len(roh) < BILD:
                        break
                    bild = bytearray(roh)
                    nummer_setzen(bild, n & 0xFFFF)
                    warte = t0 + n / FPS - time.perf_counter()
                    if warte > 0:
                        time.sleep(warte)
                    gesendet[n & 0xFFFF] = time.time()
                    enc.stdin.write(bild)
                    enc.stdin.flush()
                    n += 1
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    enc.stdin.close()
                except OSError:
                    pass

        threading.Thread(target=fuettern, daemon=True).start()
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
            stopp.set()
            for p in (dec, enc):
                p.kill()
            log(f"Strom endet fuer {self.client_address[0]}")


stand: dict[str, dict] = {}


def bericht(o: dict, an: float, wer: str) -> str:
    art = o.get("art")
    if art == "faehig":
        stand[wer] = {"n": 0, "lat": [], "start": an}
        log(f"BROWSER {wer}: {json.dumps({k: v for k, v in o.items() if k not in ('art', 'jetzt')}, ensure_ascii=False)}")
        return "verbunden"
    if art == "fehler":
        log(f"FEHLER {wer}: {o.get('wo')}: {o.get('text')}")
        return "Fehler gemeldet"
    if art != "mess":
        return ""
    jetzt = float(o.get("jetzt") or 0.0)
    lat = []
    for n, t in o.get("proben") or []:
        ab = gesendet[int(n) & 0xFFFF]
        if ab:
            lat.append((an - (jetzt - float(t)) / 1000.0 - ab) * 1000.0)
    s = stand.setdefault(wer, {"n": 0, "lat": [], "start": an})
    s["n"] += 1
    s["lat"] += lat
    if lat:
        text = (f"Verzoegerung {sum(lat) / len(lat):.0f} ms ({min(lat):.0f} bis {max(lat):.0f}), {len(lat)} Bilder/s, "
                f"Vorrat {float(o.get('vorrat') or 0) * 1000:.0f} ms, verloren {o.get('verloren')} von {o.get('gezeigt')}")
    else:
        text = f"kein Bild gelesen (bereit {o.get('bereit')}, Lesefehler {o.get('lesefehler')}, {o.get('letzte')})"
    log(f"MESS {wer}: {text}; Bild {o.get('vw')}x{o.get('vh')}, Tempo {o.get('rate')}, Spruenge {o.get('spruenge')}, Lesefehler {o.get('lesefehler')}")
    if s["n"] % 10 == 0 and s["lat"]:
        alle = sorted(s["lat"][-250:])
        log(f"ZEHN SEKUNDEN {wer}: Verzoegerung Mitte {alle[len(alle) // 2]:.0f} ms, 95 Prozent unter {alle[int(len(alle) * 0.95)]:.0f} ms, "
            f"{len(alle) / 10:.1f} Bilder je Sekunde gezeigt")
    return text


def main() -> None:
    ENDE.unlink(missing_ok=True)
    vorbereiten()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Dienst)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"BEREIT auf Port {PORT}. Dieses Fenster offen lassen.")
    while not ENDE.exists():
        time.sleep(1)
    ENDE.unlink(missing_ok=True)
    log("BEENDET")
    server.shutdown()


if __name__ == "__main__":
    main()
