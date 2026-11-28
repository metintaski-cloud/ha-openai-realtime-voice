# Was ist im Behaelter da, um einen Videostrom zu bauen? Nur ansehen, nichts aendern.
import importlib, subprocess, socket, shutil
for m in ("aiohttp", "websockets", "aiortc", "av", "fastapi", "uvicorn", "tornado", "flask", "cv2", "numpy"):
    try:
        mod = importlib.import_module(m)
        print(m, getattr(mod, "__version__", "da"))
    except Exception as e:
        print(m, "FEHLT", type(e).__name__)
print("ffmpeg", shutil.which("ffmpeg"))
out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
for z in out.splitlines():
    if any(k in z for k in ("264", "nvenc", "vp8", "vp9", "mjpeg", "libopus", " aac")):
        print(z.strip())
print(subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0])
print("hostname", socket.gethostname())
print(subprocess.run("ip -4 addr 2>/dev/null | grep inet; cat /etc/resolv.conf | head -3; getent hosts host.docker.internal", shell=True, capture_output=True, text=True).stdout)
