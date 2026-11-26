"""Freeze the background of a Kling clip (Metin, 26 Nov 2026, 19:53, about clip 211: "hier bewegen sich die
Wolken im Hintergrund").

Kling lets the coloured fog left and right of Leyla drift whenever the first and the last frame of a clip are not
the same picture (the talk clips: entry, pose, way back), in spite of "unchanged background" in the prompt. This
tool takes the picture points left and right of her from one still frame (the "plate": the first frame of the
outfit's loops, here the first frame of PLATE_CLIP) and leaves her and the middle untouched. It works on the YUV
planes, so no colour is converted. The result has no sound; nothing is cut and the tempo stays.

Two ways per frame and side, chosen by the tool:
  column: the edge lies in the black gap between the fog and her (found from a small copy of the frame);
  matte:  when an arm or the book reaches into the columns of the fog there is no gap; then the plate is taken
          up to where the fog can reach, except for the picture points that are her (skin, gold, the book).

Run on Metin's PC (device shell, needs ffmpeg, numpy, Pillow):
  python3 wolken_ruhig.py CLIP.mp4 PLATE_CLIP.mp4 OUT.mp4
A plate of another height is scaled to the clip (clips started from an extracted frame are 3520 instead of 3524
high; measured 26 Nov 2026: scaled fits better than cropped). Look at the frames it names as "matte" before use.
"""
import subprocess, sys
import numpy as np
from PIL import Image

src, plate_src, out = sys.argv[1], sys.argv[2], sys.argv[3]
w, h = 392, 588
GAP = 3  # columns of the small copy that must lie between fog and figure for the column way

def probe(p):
    o = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                 'stream=width,height', '-of', 'csv=p=0', p]).decode().strip().split(',')
    return int(o[0]), int(o[1])

def raw(p, vf, pix, frames=None):
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-i', p, '-vf', vf] + (['-frames:v', str(frames)] if frames else []) \
        + ['-pix_fmt', pix, '-f', 'rawvideo', '-']
    return np.frombuffer(subprocess.check_output(cmd), dtype=np.uint8)

W, H = probe(src)
S = W / w
small = raw(src, f'scale={w}:{h}', 'rgb24').reshape(-1, h, w, 3)
plate_small = raw(plate_src, f'scale={w}:{h}', 'rgb24', 1).reshape(h, w, 3)
plate = raw(plate_src, f'scale={W}:{H}:flags=bicubic', 'yuv420p', 1)
ysz, csz = W * H, (W // 2) * (H // 2)
pY = plate[:ysz].reshape(H, W).astype(np.float32)
pU = plate[ysz:ysz + csz].reshape(H // 2, W // 2).astype(np.float32)
pV = plate[ysz + csz:].reshape(H // 2, W // 2).astype(np.float32)

def masks(f):
    f = f.astype(np.int16); r, g, b = f[..., 0], f[..., 1], f[..., 2]; mx = f.max(-1); mn = f.min(-1)
    fog = (mx > 28) & ((b > r + 12) | ((g < b - 8) & (g < r - 8)))
    fig = ((mx > 45) & (r > b + 12) & (g > b + 4)) | ((mx > 110) & (mx - mn < 45))  # skin and gold, or the book
    return fog, fig

def spans(fog, fig, pl, pr):
    x = np.where(fig.sum(0) >= 3)[0]; fl, fr = int(x.min()), int(x.max())
    x = np.where(fog.sum(0) >= 2)[0]
    # the fog's reach on each side: fog coloured columns near the plate's fog only (the black dress
    # mirrors the blue light, that is not fog; measured: the fog drifts at most 12 columns further in)
    xl = x[x <= pl + 15]; xr = x[x >= pr - 15]
    return (max(int(xl.max()) if len(xl) else pl, pl), fl, fr, min(int(xr.min()) if len(xr) else pr, pr))

pf, pg = masks(plate_small)
x = np.where(pg.sum(0) >= 3)[0]; c = np.where(pf.sum(0) >= 2)[0]
PL, PR = int(c[c < x.min()].max()), int(c[c > x.max()].min())
PFL, PFR = int(x.min()), int(x.max())  # she herself in the plate: nothing of the plate is taken between these
M = [masks(small[i]) for i in range(len(small))]
E = np.array([spans(fo, fi, PL, PR) for fo, fi in M], dtype=float)
xs = (np.arange(W) + 0.5) / S

def dilate(m, n=2):
    o = m.copy()
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            o |= np.roll(np.roll(m, dy, 0), dx, 1)
    return o

def side(i, left):
    """Share of the plate for one side of frame i: a row of W values (column way) or a full picture (matte)."""
    lo, hi = max(0, i - 2), min(len(E), i + 3)
    if left:
        fog, fig = E[lo:hi, 0].max(), E[lo:hi, 1].min()
        inner, outer = min(fig, PFL - 2), fog      # the edge must lie between the fog and her, in the
    else:                                          # frame and in the plate (her elbow in the plate left a
        fog, fig = E[lo:hi, 3].min(), E[lo:hi, 2].max()   # dark ghost beside the book in the first try)
        inner, outer = max(fig, PFR + 2), fog
    gap = (inner - outer) if left else (outer - inner)
    if gap >= GAP:
        c = (inner + outer) / 2; f = max(0.5, min(4.0, gap / 2 - 0.5))
        a = np.clip((c + f - xs) / (2 * f), 0, 1) if left else np.clip((xs - (c - f)) / (2 * f), 0, 1)
        return a.astype(np.float32), False
    # matte: plate up to the fog's reach plus a little, but never over her
    reach = min(fog + 3, PFL - 2) if left else max(fog - 3, PFR + 2)
    zone = np.clip((reach + 1.5 - xs) / 3, 0, 1) if left else np.clip((xs - (reach - 1.5)) / 3, 0, 1)
    keep = np.zeros((h, w), bool)
    for j in range(lo, hi):
        keep |= M[j][1]
    keep = dilate(keep, 2)
    up = np.asarray(Image.fromarray((keep * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), dtype=np.float32) / 255
    return (zone[None, :].astype(np.float32) * (1 - up)), True

dec = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-i', src, '-pix_fmt', 'yuv420p', '-f', 'rawvideo', '-'],
                       stdout=subprocess.PIPE)
enc = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', f'{W}x{H}',
                        '-r', '24', '-i', '-', '-c:v', 'libx264', '-preset', 'fast', '-crf', '15', '-profile:v', 'main',
                        '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709', '-color_trc', 'bt709',
                        '-color_primaries', 'bt709', '-an', out], stdin=subprocess.PIPE)
n, fsz, matte = 0, ysz + 2 * csz, []
while True:
    buf = dec.stdout.read(fsz)
    if len(buf) < fsz:
        break
    fr = np.frombuffer(buf, dtype=np.uint8)
    al, ml = side(n, True); ar, mr = side(n, False)
    if ml or mr:
        matte.append(n)
        A = np.maximum(al if al.ndim == 2 else al[None, :], ar if ar.ndim == 2 else ar[None, :])
        A = np.broadcast_to(A, (H, W))
        Ac = A.reshape(H // 2, 2, W // 2, 2).mean((1, 3))
    else:
        A = np.maximum(al, ar)[None, :]
        Ac = A.reshape(1, W // 2, 2).mean(2)
    Y = fr[:ysz].reshape(H, W).astype(np.float32)
    U = fr[ysz:ysz + csz].reshape(H // 2, W // 2).astype(np.float32)
    V = fr[ysz + csz:].reshape(H // 2, W // 2).astype(np.float32)
    Y += (pY - Y) * A; U += (pU - U) * Ac; V += (pV - V) * Ac
    for p in (Y, U, V):
        enc.stdin.write(np.rint(p).astype(np.uint8).tobytes())
    n += 1
enc.stdin.close(); enc.wait(); dec.wait()
gl = (E[:, 1] - E[:, 0]); gr = (E[:, 3] - E[:, 2])
print(f'{W}x{H} frames {n} plate fog {PL}/{PR} smallest gap left {gl.min():.0f} (frame {gl.argmin()}) right {gr.min():.0f} '
      f'(frame {gr.argmin()}) matte frames {len(matte)}: {matte[:1]}..{matte[-1:]}' if matte else
      f'{W}x{H} frames {n} plate fog {PL}/{PR} smallest gap left {gl.min():.0f} right {gr.min():.0f}, no matte frames')
if matte:
    print('matte', matte)
