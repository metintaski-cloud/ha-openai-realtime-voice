"""Freeze the background of a Kling clip (Metin, 26 Nov 2026, 19:53, about clip 211: "hier bewegen sich die
Wolken im Hintergrund").

Kling lets the coloured fog left and right of Leyla drift whenever the first and the last frame of a clip are not
the same picture (the talk clips: entry, pose, way back), in spite of "unchanged background" in the prompt. This
tool takes the picture points left and right of her from one still frame (the "plate": the first frame of the
outfit's loops) and leaves her and the middle untouched. The edge of each side lies in the black gap between the
fog and her, found for every frame from a small copy. It works on the YUV planes, so no colour is converted.

Run on Metin's PC (device shell, needs ffmpeg and numpy). Steps:
  ffmpeg -i CLIP.mp4 -vf scale=392:588 -pix_fmt rgb24 -f rawvideo small.rgb
  ffmpeg -i PLATE_CLIP.mp4 -frames:v 1 -pix_fmt yuv420p -f rawvideo plate.yuv
  python3 wolken_ruhig.py CLIP.mp4 plate.yuv small.rgb OUT.mp4 0 9999
PL and PR are the columns (in the small copy) up to which the fog of the plate reaches; they were measured for
the short Freizeit dress and have to be measured again for another picture. Check before use that the gap
between fog and figure is there in every frame (5 columns at least in clips 134 and 211). The result is a new
file without sound; the original stays in "Leyla Kling Originale" and nothing is cut or changed in tempo.
"""
import subprocess, sys
import numpy as np
src, plate_p, small_p, out, a, b = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
W, H = 2352, 3524
w, h = 392, 588
S = W // w
small = np.memmap(small_p, dtype=np.uint8, mode='r').reshape(-1, h, w, 3)
PL, PR = 93, 303   # fog of the plate: on the left up to column 93, on the right from 303 (small copy)

def edges(f):
    f = f.astype(np.int16); r, g, bl = f[..., 0], f[..., 1], f[..., 2]; mx = f.max(-1)
    fog = (mx > 28) & ((bl > r + 12) | ((g < bl - 8) & (g < r - 8)))
    fig = (mx > 45) & (r > bl + 12) & (g > bl + 4)
    x = np.where(fig.sum(0) >= 3)[0]; fl, fr = x.min(), x.max()
    x = np.where(fog.sum(0) >= 2)[0]
    xl = x[x < fl]; xr = x[x > fr]
    L = max(int(xl.max()) if len(xl) else PL, PL); R = min(int(xr.min()) if len(xr) else PR, PR)
    return L, fl, fr, R

E = np.array([edges(small[i]) for i in range(len(small))], dtype=float)
def alpha(i):
    """Share of the plate per column (full width) for frame i; the edge lies in the gap between fog and
    figure, taken to the safe side over the neighbouring frames."""
    lo, hi = max(0, i - 2), min(len(E), i + 3)
    L = E[lo:hi, 0].max(); FL = E[lo:hi, 1].min(); FR = E[lo:hi, 2].max(); R = E[lo:hi, 3].min()
    x = (np.arange(W) + 0.5) / S
    cl = (L + FL) / 2; fl = max(0.5, min(4.0, (FL - L) / 2 - 0.5))
    cr = (FR + R) / 2; fr = max(0.5, min(4.0, (R - FR) / 2 - 0.5))
    al = np.clip((cl + fl - x) / (2 * fl), 0, 1)
    ar = np.clip((x - (cr - fr)) / (2 * fr), 0, 1)
    return np.maximum(al, ar).astype(np.float32), (L, FL, FR, R)

plate = np.fromfile(plate_p, dtype=np.uint8)
ysz, csz = W * H, (W // 2) * (H // 2)
pY = plate[:ysz].reshape(H, W).astype(np.float32)
pU = plate[ysz:ysz + csz].reshape(H // 2, W // 2).astype(np.float32)
pV = plate[ysz + csz:].reshape(H // 2, W // 2).astype(np.float32)
dec = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-i', src, '-vf', f"select='between(n\\,{a}\\,{b})'",
                        '-vsync', '0', '-pix_fmt', 'yuv420p', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
enc = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', f'{W}x{H}',
                        '-r', '24', '-i', '-', '-c:v', 'libx264', '-preset', sys.argv[7] if len(sys.argv) > 7 else 'fast',
                        '-crf', '15', '-profile:v', 'main', '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709',
                        '-color_trc', 'bt709', '-color_primaries', 'bt709', '-an', out], stdin=subprocess.PIPE)
n = a
fsz = ysz + 2 * csz
while True:
    buf = dec.stdout.read(fsz)
    if len(buf) < fsz:
        break
    fr = np.frombuffer(buf, dtype=np.uint8)
    al, _ = alpha(n)
    Y = fr[:ysz].reshape(H, W).astype(np.float32)
    U = fr[ysz:ysz + csz].reshape(H // 2, W // 2).astype(np.float32)
    V = fr[ysz + csz:].reshape(H // 2, W // 2).astype(np.float32)
    ac = al.reshape(-1, 2).mean(1)
    Y += (pY - Y) * al[None, :]
    U += (pU - U) * ac[None, :]
    V += (pV - V) * ac[None, :]
    enc.stdin.write(np.rint(Y).astype(np.uint8).tobytes())
    enc.stdin.write(np.rint(U).astype(np.uint8).tobytes())
    enc.stdin.write(np.rint(V).astype(np.uint8).tobytes())
    n += 1
enc.stdin.close(); enc.wait(); dec.wait()
print('frames', n - a)
