"""Make a stage clip: Kling mark removed, 720 wide, cut at the frame closest to the first one."""
import json, subprocess, sys
import numpy as np
src, dst = sys.argv[1], sys.argv[2]
info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
       "stream=width,height,r_frame_rate", "-of", "json", src]))["streams"][0]
W, H = info["width"], info["height"]
num, den = map(int, info["r_frame_rate"].split("/")); fps = num / den
raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", src, "-vf", "scale=64:96,format=gray", "-f", "rawvideo", "-"])
fr = np.frombuffer(raw, np.uint8).reshape(-1, 96, 64).astype(np.float32)
d = ((fr - fr[0]) ** 2).mean(axis=(1, 2))
start = int(len(fr) * 0.55)
best = start + int(np.argmin(d[start:]))
t = best / fps
print(f"{src.split('/')[-1]}: frames {len(fr)}, best end {best} ({t:.2f}s), diff {d[best]:.0f} vs mean {d[1:].mean():.0f}")
x, y, w, h = round(608 / 784 * W), round(1112 / 1176 * H), round(162 / 784 * W), round(44 / 1176 * H)
subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-i", src, "-t", f"{t:.3f}", "-vf",
    f"delogo=x={x}:y={y}:w={w}:h={h}", "-an", "-c:v", "libx264", "-preset", "veryfast",
    "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst])
