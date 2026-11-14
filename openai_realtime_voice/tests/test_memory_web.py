import asyncio
import json

from app import memory, memory_web


def _store(tmp_path):
    s = memory.MemoryStore(str(tmp_path / "memory.json"))
    s.save_all({"family": ["a", "b", "c"], "friends": ["f1"], "leyla": ["l1"],
                "private": ["geheim"]})
    return s


def test_snapshot_hides_private(tmp_path):
    snap = memory_web.snapshot(_store(tmp_path))
    assert [x["kind"] for x in snap["lists"]] == ["family", "friends", "leyla"]
    assert "geheim" not in json.dumps(snap)


def test_delete_only_open_lists(tmp_path):
    s = _store(tmp_path)
    n = memory_web.delete_items(s, [{"kind": "family", "text": "b"},
                                    {"kind": "leyla", "text": "l1"},
                                    {"kind": "private", "text": "geheim"},
                                    {"kind": "family", "text": "nope"}, "junk"])
    assert n == 2
    assert s.load("family") == ["a", "c"] and s.load("leyla") == []
    assert s.load("private") == ["geheim"]


def test_http_roundtrip(tmp_path):
    s = _store(tmp_path)
    kicked = []

    class Sync:
        def kick(self):
            kicked.append(1)

    async def call(port, raw):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(raw)
        await w.drain()
        data = await r.read()
        w.close()
        return data.decode()

    async def go():
        server = await memory_web.start_http(s, Sync(), host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        page = await call(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        lists = await call(port, b"GET /api/lists HTTP/1.1\r\nHost: x\r\n\r\n")
        body = json.dumps({"items": [{"kind": "family", "text": "a"}]}).encode()
        post = await call(port, b"POST /api/delete HTTP/1.1\r\nContent-Length: "
                          + str(len(body)).encode() + b"\r\n\r\n" + body)
        bad = await call(port, b"GET /x HTTP/1.1\r\n\r\n")
        server.close()
        return page, lists, post, bad

    page, lists, post, bad = asyncio.run(go())
    assert "Markierte" in page and '"family"' in lists
    assert '"removed": 1' in post and kicked == [1]
    assert s.load("family") == ["b", "c"]
    assert "404" in bad


def test_edit_item(tmp_path):
    s = _store(tmp_path)
    assert memory_web.edit_item(s, "family", "b", "  neuer   Text ")
    assert s.load("family") == ["a", "neuer Text", "c"]
    assert not memory_web.edit_item(s, "family", "a", "c")  # duplicate
    assert not memory_web.edit_item(s, "family", "a", "   ")  # empty
    assert not memory_web.edit_item(s, "family", "a", "x" * 701)  # too long
    assert not memory_web.edit_item(s, "family", "gibts nicht", "y")
    assert not memory_web.edit_item(s, "private", "geheim", "y")
    assert s.load("private") == ["geheim"]


def test_move_items(tmp_path):
    s = _store(tmp_path)
    ok = memory_web.move_items(s, {"family": ["c", "a"], "friends": ["f1", "b"], "leyla": ["l1"]})
    assert ok and s.load("family") == ["c", "a"] and s.load("friends") == ["f1", "b"]
    assert s.load("private") == ["geheim"]
    # something lost, something new, wrong shape: refused, nothing changes
    assert not memory_web.move_items(s, {"family": ["c"], "friends": ["f1", "b"], "leyla": ["l1"]})
    assert not memory_web.move_items(s, {"family": ["c", "a", "x"], "friends": ["f1", "b"], "leyla": ["l1"]})
    assert not memory_web.move_items(s, {"family": "c", "friends": [], "leyla": []})
    assert s.load("family") == ["c", "a"]


def test_icon_and_manifest(tmp_path):
    s = _store(tmp_path)

    async def go():
        server = await memory_web.start_http(s, None, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"GET /icon.png HTTP/1.1\r\n\r\n")
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return data

    data = asyncio.run(go())
    assert data.startswith(b"HTTP/1.1 200") and b"image/png" in data and b"\x89PNG" in data
    assert "/icon.png?v=" in memory_web.MANIFEST and "/icon.png?v=" in memory_web.PAGE


def test_page_has_sounds():
    assert "AudioContext" in memory_web.PAGE and 'id="snd"' in memory_web.PAGE


def test_page_has_splash():
    assert 'id="splash"' in memory_web.PAGE and "stroke-dashoffset" in memory_web.PAGE
