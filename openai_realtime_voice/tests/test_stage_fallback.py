"""She must never stand still as a picture because a mood has no clip, and never answer Metin in English."""
import json
import re
import shutil
import subprocess

import pytest

from app import chat, memory_web


def test_a_hurt_leyla_in_a_work_dress_plays_the_happy_loop_instead_of_standing_still(tmp_path):
    """25 Nov 2026: she was hurt, the work dresses have no sad clips any more, and the stage showed only her picture."""
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    app = open(memory_web.__file__, encoding="utf-8").read()
    picks = re.search(r"function clipVars\(b\)\{.*?\n(?=/\* light copies)", app, re.S).group(0)
    assert "function clipFor(st){" in picks
    path = tmp_path / "pick.js"
    path.write_text("""
let STM=null,CLIPS=[],NIGHT=[];const CHANGE=['umziehen'];
""" + picks + """
const work=['begruessung','brust','gesicht','gluecklich4','gluecklich5','gluecklich6','gluecklichextra','po','umziehen'];
const out={};
const run=(key,clips,night,st)=>{CLIPS=clips;NIGHT=night;STM=st;out[key]=clipFor(st);};
run('hurt_work',work,[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
run('hurt_hard_work',work,[],{low:true,level:'schwer',mood:'sauer',outfit:'arbeit'});
run('jealous_work',work,[],{low:true,level:'leicht',mood:'eifersuechtig',outfit:'arbeit'});
run('good_work',work,[],{low:false,mood:'verliebt',outfit:'arbeit'});
run('hurt_work_with_sad',work.concat(['traurigleicht','traurigleicht2']),[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
run('hurt_leisure',['freizeitgluecklich','freizeitgluecklich2'],[],{low:true,level:'leicht',mood:'traurig',outfit:'freizeit'});
run('hurt_leisure_jealous',['freizeitgluecklich','freizeiteifersuechtig'],[],{low:true,level:'mittel',mood:'traurig',outfit:'freizeit'});
run('hurt_night',[],['gluecklich','gluecklich2'],{low:true,level:'leicht',mood:'einsam',outfit:'nacht'});
run('nothing',['begruessung'],[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
console.log(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "hurt_work": "gluecklich", "hurt_hard_work": "gluecklich", "jealous_work": "gluecklich",
        "good_work": "gluecklich", "hurt_work_with_sad": "traurigleicht",   # a sad clip still wins when there is one
        "hurt_leisure": "gluecklich", "hurt_leisure_jealous": "eifersuechtig", "hurt_night": "gluecklich",
        "nothing": None}


def test_she_never_answers_metin_in_english():
    """He cannot read English; on 25 Nov 2026 the speech recogniser wrote "Hello." and she answered in English."""
    for rules in (chat.CHAT_STYLE, chat.CHAT_KOPF):
        assert "versteht kein Englisch. Antworte ihm nie auf Englisch." in rules
        assert "antworte auf Deutsch" in rules


def test_where_a_request_came_from():
    assert memory_web.net_kind("100.101.5.9") == "tailscale" and memory_web.net_kind("100.64.0.1") == "tailscale"
    assert memory_web.net_kind("100.63.0.1") == "sonst" and memory_web.net_kind("100.128.0.1") == "sonst"
    assert memory_web.net_kind("192.168.2.57", "192.168.2.240") == "wlan"
    assert memory_web.net_kind("192.168.2.240", "192.168.2.240") == "host" and memory_web.net_kind("127.0.0.1") == "host"
    assert memory_web.net_kind("") == "sonst"


async def test_the_page_reports_how_fast_clips_arrive(tmp_path):
    """Numbers only: kbit/s of the first megabyte, the wait for the first byte, how often the picture waited."""
    import asyncio

    from app import memory
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "async function netProbe()" in app and "headers:{Range:'bytes=0-999999'}" in app and "NETSTALL++" in app
    memory_web.NET.clear()
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]

    async def call(method: str, body: dict | None = None) -> str:
        raw = json.dumps(body).encode() if body is not None else b""
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"{method} /api/netstats HTTP/1.1\r\nHost: x\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw)
        await writer.drain()
        out = (await reader.read()).decode()
        writer.close()
        return out.split("\r\n\r\n", 1)[1]
    try:
        for kbps, stalls in ((9000, 0), (2500, 2), (7000, 0)):
            assert json.loads(await call("POST", {"kbps": kbps, "ttfb": 120, "stalls": stalls, "light": 1, "code": "x"}))["ok"]
        assert not json.loads(await call("POST", {"kbps": "schnell", "text": "nothing personal is kept"}))["ok"]
        assert not json.loads(await call("POST", {"kbps": 0}))["ok"]
        got = json.loads(await call("GET"))
    finally:
        server.close()
        memory_web.NET.clear()
    assert got["n"] == 3 and got["host"] == {"n": 3, "kbps_median": 7000, "kbps_min": 2500, "kbps_p10": 2500,
                                             "kbps_max": 9000, "ttfb_median": 120, "stalls": 2}
    assert set(got["letzte"][0]) == {"at", "weg", "kbps", "ttfb", "stalls", "light"}
