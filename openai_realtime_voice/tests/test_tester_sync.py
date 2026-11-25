"""Clip tester: the reference on the left runs in step with the clip on the right (2.173.2, Metin, 26 Nov 2026:
"da soll zusätzlich Referenz Clip links genau synchron laufen mit Clip rechts", "dass alle Clips synchron laufen")."""
import asyncio
import shutil
import subprocess

import pytest

from app import memory, memory_web


def _clip(path, seconds):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=160x240:rate=24:duration={seconds}", "-c:v", "libx264", "-preset", "veryfast",
                    "-g", "6", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True)


async def test_in_a_browser_the_reference_starts_with_the_clip_and_starts_over_with_it(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        _clip(folder / "lang.mp4", 8)    # the reference, longer than the clip under test
        _clip(folder / "po.mp4", 3)
        _clip(folder / "ruhig.mp4", 6)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    for key in ("TEMPO", "KURVE", "SCHNITT", "VORLAUF"):
        monkeypatch.setenv("LEYLA_" + key, str(tmp_path / (key + ".json")))
    assert memory_web._schnitt_set("kurz/ruhig", 0.5, 1.5)   # this one, as reference, is through after one second
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    watch = """async(ms)=>{const [l,r]=document.querySelectorAll('video'),S=[],t0=performance.now();
      await new Promise(done=>{const f=()=>{S.push([l.currentTime,r.currentTime,l.paused?1:0]);if(performance.now()-t0<ms)requestAnimationFrame(f);else done();};f();});return S;}"""
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 900, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.add_init_script("try{localStorage.setItem('lref','kurz/lang');}catch(e){}")
            await page.goto(f"http://127.0.0.1:{port}/tempo?clip=kurz/po")
            await page.wait_for_function("()=>{const v=document.querySelectorAll('video');return v.length===2&&v[0].duration>0&&v[1].duration>0&&v[1].currentTime>0.3;}")
            long_ref = await page.evaluate(watch, 4500)     # the 3 s clip starts over at least once
            # now a reference that is through first: it holds its last picture and waits for the clip
            await page.close()
            page = await browser.new_page(viewport={"width": 900, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.add_init_script("try{localStorage.setItem('lref','kurz/ruhig');}catch(e){}")
            await page.goto(f"http://127.0.0.1:{port}/tempo?clip=kurz/po")
            await page.wait_for_function("()=>{const v=document.querySelectorAll('video');return v.length===2&&v[0].duration>0&&v[1].duration>0&&v[1].currentTime>0.3;}")
            short_ref = await page.evaluate(watch, 4500)
            await browser.close()
    finally:
        server.close()
    assert errors == []
    # 1. in step from the start: both are at the same place while the clip plays its first pass
    gaps = [abs(l - r) for l, r, _ in long_ref[:20]]
    assert max(gaps) < 0.12, max(gaps)
    # 2. when the clip on the right starts over, the reference starts over in the same moment (never past 3.2 s
    #    although the reference is 8 s long), and they stay together afterwards
    wraps = [i for i in range(1, len(long_ref)) if long_ref[i][1] < long_ref[i - 1][1] - 1]
    assert wraps and max(l for l, _, _ in long_ref) < 3.2, (len(wraps), max(l for l, _, _ in long_ref))
    after = [abs(l - r) for l, r, _ in long_ref[wraps[0] + 8:wraps[0] + 30]]
    assert after and max(after) < 0.12, max(after)
    # 3. a reference that is through first begins at its own begin mark, holds at its end mark and starts over with the clip
    lefts = [l for l, _, _ in short_ref]
    assert min(lefts) > 0.4 and max(lefts) < 1.62, (min(lefts), max(lefts))
    assert any(paused for _, _, paused in short_ref), "it waits at its end"
    wraps = [i for i in range(1, len(short_ref)) if short_ref[i][1] < short_ref[i - 1][1] - 1]
    assert wraps and any(l < 0.75 for l, _, _ in short_ref[wraps[0]:wraps[0] + 12]), "and starts over with the clip"
