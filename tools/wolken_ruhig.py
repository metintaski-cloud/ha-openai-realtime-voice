"""Freeze the background of a Kling clip (Metin, 26 Nov 2026, 19:53, about clip 211: "hier bewegen sich die
Wolken im Hintergrund").

Kling lets the coloured fog left and right of Leyla drift whenever the first and the last frame of a clip are not
the same picture (the talk clips: entry, pose, way back), in spite of "unchanged background" in the prompt. This
tool takes the picture points left and right of her from one still frame (the "plate": the first frame of the
outfit's loops, here the first frame of PLATE_CLIP) and leaves her and the middle untouched. It works on the YUV
planes, so no colour is converted. The result has no sound; nothing is cut and the tempo stays.

How: on each side the plate is taken up to where the fog can reach, except for every picture point of the frame
or of the plate that is something else than fog or black and hangs together with her (her skin, gold, the book,
the hems and the sheen of the dress; the region is found on a small copy, her exact outline at full size; grey
patches inside the smoke do not hang together with her and are replaced). So an arm or the book may reach into
the fog, and she herself in the plate (her elbow, the train of the long dress) is never copied into the picture.

Run on Metin's PC (device shell, needs ffmpeg, numpy, Pillow):
  python3 wolken_ruhig.py CLIP.mp4 PLATE_CLIP.mp4 OUT.mp4
A plate of another height is scaled to the clip (clips started from an extracted frame are 3520 instead of 3524
high; measured 26 Nov 2026: scaled fits better than cropped). Look at a contact sheet of the result before use.
"""
import subprocess, sys
import numpy as np
from PIL import Image, ImageFilter

src, plate_src, out = sys.argv[1], sys.argv[2], sys.argv[3]
w, h = 392, 588

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
    """fog: the coloured fog and its glow on the floor. thing: everything else that is not black
    (her skin, gold, the book, hems, the sheen of the dress, lines on the floor)."""
    f = f.astype(np.int16); r, g, b = f[..., 0], f[..., 1], f[..., 2]; mx = f.max(-1)
    fog = (mx > 28) & ((b > r + 12) | ((g < b - 8) & (g < r - 8)))
    thing = (mx > 22) & ~fog
    return fog, thing

def dilate(m, n=2):
    o = m.copy()
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            o |= np.roll(np.roll(m, dy, 0), dx, 1)
    return o

TOP = int(h * 0.6)   # the fog itself stands in the upper part; below are its glow and the dress
pf, pt = masks(plate_small)
c = pf[:TOP].sum(0)  # the dress mirrors the blue light in a few points; fog fills its columns
PL = int(np.where(c[:w // 2] >= 8)[0].max()); PR = int(np.where(c[w // 2:] >= 8)[0].min()) + w // 2

def body(thing):
    """Of everything that is not fog and not black, only what hangs together with her in the middle:
    the smoke has grey patches of its own, and those must not be kept (first try: half of the fog
    stayed as it was)."""
    seed = thing.copy(); seed[:, :PL + 16] = False; seed[:, PR - 15:] = False
    n = int(seed.sum())
    while True:
        seed = dilate(seed, 2) & thing
        m = int(seed.sum())
        if m == n:
            return seed
        n = m

GP = dilate(body(pt), 2)   # where she and her dress stand in the plate (small copy)
M = [(fo, dilate(body(th), 2)) for fo, th in (masks(small[i]) for i in range(len(small)))]

def fine(Yp, Up, gate, x0, x1):
    """Her exact outline between the columns x0 and x1 at full size: inside the coarse region `gate`
    (small copy) every picture point that is neither black nor fog coloured. The first try used the
    coarse region itself and left a blocky dark rim around her hand in front of the fog."""
    g = np.asarray(Image.fromarray(gate.astype(np.uint8) * 255).resize((W, H), Image.NEAREST))[:, x0:x1] > 0
    u = np.repeat(np.repeat(Up, 2, 0), 2, 1)[:, x0:x1]
    k = g & (Yp[:, x0:x1] > 22) & (u < 133)
    return np.asarray(Image.fromarray(k.astype(np.uint8) * 255).filter(ImageFilter.BoxBlur(2)), dtype=np.float32) / 255

def reach(fog):
    """How far in the fog of one frame reaches on each side (columns near the plate's fog only;
    measured: it drifts at most 12 columns further in)."""
    x = np.where(fog[:TOP].sum(0) >= 2)[0]
    xl = x[x <= PL + 15]; xr = x[x >= PR - 15]
    return max(int(xl.max()) if len(xl) else PL, PL), min(int(xr.min()) if len(xr) else PR, PR)

R = np.array([reach(fo) for fo, _ in M], dtype=float)
xs = (np.arange(W) + 0.5) / S

def alpha(i, Y, U):
    """Share of the plate for frame i, a full picture: the plate up to where the fog can reach on
    each side, except where she stands in the frame or in the plate."""
    lo, hi = max(0, i - 2), min(len(M), i + 3)
    rl = R[lo:hi, 0].max() + 3; rr = R[lo:hi, 1].min() - 3
    A = np.maximum(np.clip((rl + 1.5 - xs) / 3, 0, 1), np.clip((xs - (rr - 1.5)) / 3, 0, 1)).astype(np.float32)
    A = np.repeat(A[None, :], H, 0)
    xl = int((rl + 3) * S) // 2 * 2; xr = int((rr - 3) * S) // 2 * 2
    for x0, x1 in ((0, xl), (xr, W)):
        keep = np.maximum(fine(Y, U, M[i][1], x0, x1), fine(pY, pU, GP, x0, x1))
        A[:, x0:x1] *= 1 - keep
    return A

dec = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-i', src, '-pix_fmt', 'yuv420p', '-f', 'rawvideo', '-'],
                       stdout=subprocess.PIPE)
enc = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', f'{W}x{H}',
                        '-r', '24', '-i', '-', '-c:v', 'libx264', '-preset', 'fast', '-crf', '15', '-profile:v', 'main',
                        '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709', '-color_trc', 'bt709',
                        '-color_primaries', 'bt709', '-an', out], stdin=subprocess.PIPE)
n, fsz = 0, ysz + 2 * csz
while True:
    buf = dec.stdout.read(fsz)
    if len(buf) < fsz:
        break
    fr = np.frombuffer(buf, dtype=np.uint8)
    Y = fr[:ysz].reshape(H, W).astype(np.float32)
    U = fr[ysz:ysz + csz].reshape(H // 2, W // 2).astype(np.float32)
    V = fr[ysz + csz:].reshape(H // 2, W // 2).astype(np.float32)
    A = alpha(n, Y, U)
    Ac = A.reshape(H // 2, 2, W // 2, 2).mean((1, 3))
    Y += (pY - Y) * A; U += (pU - U) * Ac; V += (pV - V) * Ac
    for p in (Y, U, V):
        enc.stdin.write(np.rint(p).astype(np.uint8).tobytes())
    n += 1
enc.stdin.close(); enc.wait(); dec.wait()
print(f'{W}x{H} frames {n} plate fog up to {PL} and from {PR}, fog of the clip up to {R[:, 0].max():.0f} and from {R[:, 1].min():.0f}')
