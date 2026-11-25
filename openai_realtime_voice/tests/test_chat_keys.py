"""Typing to her on a PC (2.172.3, Metin, 25 Nov 2026): Enter sends the text, and the abc pill stays as he set
it until he clicks it again. On the phone nothing changes: Enter is a new line and after sending the field goes
back to dictation (2.140.0)."""
import asyncio

import pytest

from app import memory, memory_web

OPEN = """()=>{const sp=document.getElementById('splash');if(sp)sp.remove();CODE='x';
  post=async()=>({json:async()=>null});   // no server answer needed here
  document.getElementById('chat').style.display='block';document.body.classList.add('chatfull');}"""
STATE = """()=>{const ta=document.getElementById('ctext');return {text:ta.value,readonly:ta.readOnly,
  abc:document.getElementById('ckb').classList.contains('on'),focus:document.activeElement===ta,
  sent:CHAT.filter(m=>m.role==='user').map(m=>m.text)};}"""


async def test_in_a_browser_enter_sends_on_a_pc_and_abc_stays(tmp_path):
    playwright = pytest.importorskip("playwright.async_api")
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                pytest.skip("no browser here")
            # a PC: mouse and keyboard
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(0.5)
            await page.evaluate(OPEN)
            assert await page.evaluate("()=>DESK") is True
            box_pc = await page.evaluate("""()=>{const ta=document.getElementById('ctext'),w=()=>{const r=ta.getBoundingClientRect();return [Math.round(r.width),Math.round(r.height)];};
              const o={can:CSS.supports('field-sizing','content'),empty:w()};ta.value='Hallo';o.short=w();ta.value='Hallo Leyla, wie war dein Tag heute so?';o.line=w();
              ta.value='Das ist ein langer Text, der nicht mehr in eine Zeile passt und deshalb umbrechen muss, so wie ihre Blasen es auch tun.';o.long=w();
              ta.value='x '.repeat(900);o.huge=w();ta.value='';o.again=w();return o;}""")
            await page.click("#ckb")
            await page.keyboard.type("Hallo Leyla")
            await page.keyboard.press("Shift+Enter")
            await page.keyboard.type("zweite Zeile")
            mid = await page.evaluate(STATE)
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.2)
            pc = await page.evaluate(STATE)
            await page.keyboard.type("noch eine")   # he goes on typing without a click
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")      # an empty field sends nothing
            await asyncio.sleep(0.2)
            pc2 = await page.evaluate(STATE)
            await page.click("#ckb")                # only his click switches back
            pc3 = await page.evaluate(STATE)
            # the menu leads to the page Naht (Metin: he wants to reach it from the PC), and that page leads back
            menu = await page.evaluate("()=>{menuOpen=true;drawMenu();return [...document.querySelectorAll('#menu .mi span')].map(x=>x.textContent);}")
            # 2.173.0 (Metin): it opens in a window of its own, the app stays open beside it
            async with page.expect_popup() as pop:
                await page.evaluate("()=>[...document.querySelectorAll('#menu .mi')].find(b=>b.textContent.includes('Naht')).click()")
            naht = await pop.value
            await naht.wait_for_url("**/naht")
            back = await naht.evaluate("()=>[...document.querySelectorAll('a')].map(a=>a.getAttribute('href'))")
            stays = page.url
            await naht.close()
            await page.close()
            # a phone: touch, no mouse
            ctx = await browser.new_context(viewport={"width": 400, "height": 820}, has_touch=True, is_mobile=True)
            page = await ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(0.5)
            await page.evaluate(OPEN)
            assert await page.evaluate("()=>DESK") is False
            box_phone = await page.evaluate("()=>Math.round(document.getElementById('ctype').getBoundingClientRect().width)")
            await page.evaluate("()=>document.getElementById('ckb').onclick()")
            await page.keyboard.type("Hallo")
            await page.keyboard.press("Enter")
            await page.keyboard.type("du")
            ph = await page.evaluate(STATE)
            await page.evaluate("()=>document.getElementById('csend').onclick()")
            await asyncio.sleep(0.2)
            ph2 = await page.evaluate(STATE)
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
    assert mid["text"] == "Hallo Leyla\nzweite Zeile" and mid["sent"] == [], mid          # Shift and Enter: a new line
    assert pc == {"text": "", "readonly": False, "abc": True, "focus": True, "sent": ["Hallo Leyla\nzweite Zeile"]}, pc
    assert pc2["sent"] == ["Hallo Leyla\nzweite Zeile", "noch eine"] and pc2["abc"] and pc2["focus"], pc2
    assert pc3["readonly"] is True and pc3["abc"] is False, pc3
    assert "Naht: Schleifen einstellen" in menu and "/" in back, (menu, back)
    assert stays.endswith("/") and "naht" not in stays, stays
    # 2.172.4: on the monitor the box he writes in is as long as his text, like her bubbles (58 % were 1114 px);
    # on the phone it stays 58 %
    assert box_phone == 232, box_phone
    if not box_pc["can"]:
        pytest.skip("this browser cannot size a field by its content")
    e, sh, ln, lo, hu = (box_pc[k] for k in ("empty", "short", "line", "long", "huge"))
    assert 150 <= e[0] <= 260 and e[1] == 44, box_pc             # empty: the size of its hint, one line
    assert sh[0] == 150 and sh[1] == 44, box_pc                  # a short word: the smallest size
    assert sh[0] < ln[0] <= 440 and ln[1] == 44, box_pc          # it grows with the line
    assert lo[0] == 440 and lo[1] > 44, box_pc                   # at 440 px it breaks the line and grows upwards
    assert hu == [440, 110] and box_pc["again"] == e, box_pc     # never higher than 110 px, and back when empty
    assert ph["text"] == "Hallo\ndu" and ph["sent"] == [], ph                             # phone: Enter is a new line
    assert ph2["sent"] == ["Hallo\ndu"] and ph2["readonly"] is True and ph2["abc"] is False, ph2  # and back to dictation
