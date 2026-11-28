# Prueft mundkern.py mit den echten Modellen, ohne Netz und ohne Zuschauer: eine ganze Rede, Zeiten, ein Bild.
import subprocess, sys, time
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mundkern import MundKern, SR
roh = subprocess.run(["ffmpeg", "-v", "error", "-i", "/work/eingabe/leyla.wav", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
ton = np.frombuffer(roh, dtype=np.float32).copy()
kern = MundKern("/work/eingabe/tv_aermel.mp4")
rede = kern.neue_rede(ton, 0)
fertig = {}
for s in range(rede.stuecke):
    fertig.update(rede.rechne_stueck(s))
fertig.update(rede.schluss())
z = np.array(rede.zeiten) * 1000
print(f"KERNTEST: {len(fertig)} von {rede.n} Bildern, Form {fertig[0].shape}, je Stueck Mittel {z.mean():.0f} ms, Spitze {z[1:].max():.0f} ms (ohne das erste), erstes {z[0]:.0f} ms", flush=True)
cv2.imwrite("/work/ergebnis/kerntest_230.jpg", cv2.cvtColor(np.concatenate([fertig[j] for j in (8, 229, 243, 261)], axis=1), cv2.COLOR_RGB2BGR))
