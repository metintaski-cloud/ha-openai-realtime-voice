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
    assert not memory_web.edit_item(s, "family", "a", "x" * 1501)  # too long
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
    assert "AudioContext" in memory_web.PAGE and "t.id='snd'" in memory_web.PAGE


def test_page_has_splash():
    assert 'id="splash"' in memory_web.PAGE and "stroke-dashoffset" in memory_web.PAGE


def test_edit_folder(tmp_path):
    s = memory.MemoryStore(str(tmp_path / "memory.json"))
    old = "Person: Metin | Zugehörigkeit: Sohn | Alter: 45"
    s.save_all({"family": [old, "Person: Anna", "Einkauf"], "friends": [], "leyla": [], "private": ["geheim"]})
    new = memory_web.edit_folder(s, "family", old, ["Alter: 45", " Zugehörigkeit:  Sohn ", "", "Hobby: a | b"])
    assert new == "Person: Metin | Alter: 45 | Zugehörigkeit: Sohn | Hobby: a / b"  # new order, empty dropped, bar escaped
    assert s.load("family") == [new, "Person: Anna", "Einkauf"]
    assert memory_web.edit_folder(s, "family", old, ["x"]) is None  # outdated page: Leyla changed it meanwhile
    assert memory_web.edit_folder(s, "family", new, ["x" * 1500]) is None  # too long
    assert memory_web.edit_folder(s, "private", "geheim", ["x"]) is None
    assert memory_web.edit_folder(s, "family", "Person: Anna", ["Alter: 3"]) == "Person: Anna | Alter: 3"
    assert memory_web.edit_folder(s, "family", "Person: Anna | Alter: 3", []) == "Person: Anna"  # all points removed
    assert memory_web.edit_folder(s, "family", "Person: Anna", "nope") is None


def test_page_has_folders():
    assert "/api/folder" in memory_web.PAGE and "Punkt hinzufügen" in memory_web.PAGE and 'id="back"' in memory_web.PAGE


def test_maskable_icon(tmp_path):
    s = _store(tmp_path)

    async def go():
        server = await memory_web.start_http(s, None, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"GET /icon-maskable.png?v=6 HTTP/1.1\r\n\r\n")
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return data

    data = asyncio.run(go())
    assert data.startswith(b"HTTP/1.1 200") and b"\x89PNG" in data
    m = json.loads(memory_web.MANIFEST)
    assert {i["purpose"] for i in m["icons"]} == {"any", "maskable"}


def test_add_item(tmp_path):
    from app import memory, memory_web
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    assert memory_web.add_item(store, "friends", "  Person: Ali |  Zugehörigkeit: Nachbar ")
    assert store.load("friends") == ["Person: Ali | Zugehörigkeit: Nachbar"]
    assert not memory_web.add_item(store, "friends", "Person: Ali | Zugehörigkeit: Nachbar")  # duplicate
    assert not memory_web.add_item(store, "friends", "   ")
    assert not memory_web.add_item(store, "private", "geheim")  # locked without the code word
    assert not memory_web.add_item(store, "confidential", "x", memory_web.TITLES + (memory_web.PRIVATE_TITLE,))
    assert memory_web.add_item(store, "private", "geheim", memory_web.TITLES + (memory_web.PRIVATE_TITLE,))


def test_code_word_and_lock(monkeypatch):
    from app import memory_web
    monkeypatch.setitem(memory_web._code_fails, "n", 0)
    monkeypatch.setitem(memory_web._code_fails, "until", 0.0)
    assert memory_web.check_code("Sonne Mond", "Leyla Sonne Mond", now=100)
    assert memory_web.check_code("leyla, sonne mond", "Leyla Sonne Mond", now=100)
    assert not memory_web.check_code("Sonne Mond Sterne", "Leyla Sonne Mond", now=100)  # exact words only
    assert not memory_web.check_code("Sonne", "", now=100)  # no code configured: never open
    for _ in range(memory_web.CODE_MAX_FAILS - 1):
        memory_web.check_code("falsch", "Leyla Sonne Mond", now=100)
    assert not memory_web.check_code("Sonne Mond", "Leyla Sonne Mond", now=100)  # locked now
    assert memory_web.check_code("Sonne Mond", "Leyla Sonne Mond", now=100 + memory_web.CODE_LOCK_S + 1)


def test_private_list_only_with_code(tmp_path):
    from app import memory, memory_web
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["a"], "private": ["geheim"], "confidential": ["Aktuell bis 1.1.2099: x"]})
    open_kinds = [l["kind"] for l in memory_web.snapshot(store)["lists"]]
    assert "private" not in open_kinds and "confidential" not in open_kinds
    titles = memory_web.TITLES + (memory_web.PRIVATE_TITLE,)
    lists = {l["kind"]: l["items"] for l in memory_web.snapshot(store, titles)["lists"]}
    assert lists["private"] == ["geheim"] and "confidential" not in lists
    # moving a private entry needs the private list in the request; Mama's list stays untouched
    assert not memory_web.move_items(store, {"family": ["a"], "friends": [], "leyla": []}, titles)
    assert memory_web.move_items(store, {"family": ["a", "geheim"], "friends": [], "leyla": [],
                                         "private": []}, titles)
    assert store.load("confidential") == ["Aktuell bis 1.1.2099: x"]


def test_readable_rules_hide_the_code_word_and_the_memory(tmp_path):
    import os
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "test")
    from app import memory
    from app.main import LiveVoiceBridge
    bridge = LiveVoiceBridge()
    bridge.code_phrase = "Leyla Zitronenbaum"
    bridge.memory = memory.MemoryStore(str(tmp_path / "m.json"))
    bridge.memory.save_all({"family": ["Person: Metin | Alter: 45"], "private": ["Quittenkuchen"]})
    text = bridge._readable_rules()
    assert "Zitronenbaum" not in text and "(dein Codewort)" in text
    assert "Quittenkuchen" not in text and "Alter: 45" not in text and "WER DU BIST" in text


def test_new_and_changed_entries_are_marked_fresh_for_two_days(tmp_path):
    import json, time
    s = memory.MemoryStore(str(tmp_path / "m.json"))
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"family": ["Alt", "Person: Metin | Arbeit: Elektriker"],
                             "friends": [], "private": [], "leyla": []}), encoding="utf-8")
    s.save_all({"family": ["Alt", "Person: Metin | Arbeit: Elektriker"]})
    assert memory_web.snapshot(s)["fresh"] == []  # first time: nothing counts as new
    s.save_all({"family": ["Alt", "Person: Metin | Arbeit: Elektriker | Interessen: Pizza", "Neu"]})
    fresh = memory_web.snapshot(s)["fresh"]
    assert "Neu" in fresh and "Alt" not in fresh
    assert "Person: Metin | Arbeit: Elektriker | Interessen: Pizza" in fresh
    assert "Person: Metin||Interessen: Pizza" in fresh
    assert "Person: Metin||Arbeit: Elektriker" not in fresh
    assert s.fresh(now=time.time() + 3 * 24 * 3600) == set()


def test_voice_route_needs_the_code_word_and_takes_a_large_body(tmp_path, monkeypatch):
    monkeypatch.setitem(memory_web._code_fails, "n", 0)
    monkeypatch.setitem(memory_web._code_fails, "until", 0.0)
    s = _store(tmp_path)
    got = []

    async def voice(history, audio, mime):
        got.append((len(audio), mime))
        return {"heard": "hallo", "reply": "Hallo Metin", "proposals": [], "lights": [], "audio": "UklG"}

    async def go(code):
        server = await memory_web.start_http(s, None, host="127.0.0.1", port=0,
                                             code_phrase="Leyla Sonne Mond", voice=voice)
        port = server.sockets[0].getsockname()[1]
        body = json.dumps({"code": code, "audio": "A" * 300_000, "mime": "audio/webm",
                           "history": []}).encode()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"POST /api/chat_voice HTTP/1.1\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return json.loads(data.split(b"\r\n\r\n", 1)[1])

    assert asyncio.run(go("falsch")) == {"error": True} and not got
    out = asyncio.run(go("Sonne Mond"))
    assert out["reply"] == "Hallo Metin" and got == [(300_000, "audio/webm")]
    assert 'id="cmic"' in memory_web.PAGE and "/api/chat_voice" in memory_web.PAGE


def test_mail_routes_need_the_code_word(tmp_path, monkeypatch):
    from app import mail
    monkeypatch.setitem(memory_web._code_fails, "n", 0)
    monkeypatch.setitem(memory_web._code_fails, "until", 0.0)
    mailer = mail.Mailer("m@gmail.com", "pw", "Ayşe: a@b.de", path=str(tmp_path / "d.json"))
    d = mailer.draft("Ayşe", "Hallo", "Text")
    s = _store(tmp_path)

    async def go(path, code, extra=None):
        server = await memory_web.start_http(s, None, host="127.0.0.1", port=0,
                                             code_phrase="Leyla Sonne Mond", mailer=mailer)
        port = server.sockets[0].getsockname()[1]
        body = json.dumps(dict({"code": code}, **(extra or {}))).encode()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"POST " + path.encode() + b" HTTP/1.1\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return json.loads(data.split(b"\r\n\r\n", 1)[1])

    assert asyncio.run(go("/api/mail/pending", "falsch")) == {"ok": False}
    out = asyncio.run(go("/api/mail/pending", "Sonne Mond"))
    assert out["ok"] and out["drafts"][0]["to"] == "Ayşe"
    assert asyncio.run(go("/api/mail/discard", "Sonne Mond", {"id": d["id"]})) == {"ok": True}
    assert "mailCard" in memory_web.PAGE and "/api/mail/send" in memory_web.PAGE


def test_diary_folder_needs_the_code_word_and_shows_chat_and_home(tmp_path, monkeypatch):
    from app import diary
    monkeypatch.setitem(memory_web._code_fails, "n", 0)
    monkeypatch.setitem(memory_web._code_fails, "until", 0.0)
    dy = diary.Diary(str(tmp_path / "dy.json"))
    entry = {"wichtig": True, "lang": "Wir haben über den Zahnarzt gesprochen.", "mittel": "m", "kurz": "k"}
    import time
    dy.add(entry, "Metin Taskiran", "stimme", now=time.time() - 60)
    dy.add(dict(entry, lang="Im Chat geflirtet.", privat=True), "Metin", "chat", now=time.time())
    s = _store(tmp_path)

    async def go(code):
        server = await memory_web.start_http(s, None, host="127.0.0.1", port=0,
                                             code_phrase="Leyla Sonne Mond", diary=dy)
        port = server.sockets[0].getsockname()[1]
        body = json.dumps({"code": code}).encode()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"POST /api/diary HTTP/1.1\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return json.loads(data.split(b"\r\n\r\n", 1)[1])

    assert asyncio.run(go("falsch")) == {"ok": False}
    out = asyncio.run(go("Sonne Mond"))
    assert [x["src"] for x in out["items"]] == ["chat", "stimme"]  # newest first
    assert out["items"][1]["who"] == "Metin" and out["items"][0]["privat"] is True
    assert "openDiary" in memory_web.PAGE and "'Tagebuch'" in memory_web.PAGE


def test_wake_stats_count_only_wake_word_talks():
    from app import metrics
    t = 1_800_000_000
    rows = [{"event": "session_end", "ts": t, "reason": "no_speech"},
            {"event": "session_end", "ts": t + 60, "reason": "goodbye"},
            {"event": "session_end", "ts": t + 120, "reason": "no_speech", "followup": True},
            {"event": "ready", "ts": t}]
    day = metrics.wake_stats(rows)[0]
    assert day["geweckt"] == 2 and day["fehlstarts"] == 1


def test_tempo_tester_keeps_the_factor(tmp_path, monkeypatch):
    """Metin, 22.11.2026: he sets the speed in the tester and the list is read later."""
    from app import memory_web
    monkeypatch.setenv("LEYLA_TEMPO", str(tmp_path / "tempo.json"))
    assert memory_web._tempo_read() == []
    memory_web._tempo_add("kurz/freizeitgluecklich", 1.2)
    memory_web._tempo_add("nacht/tanz14", 0.8)
    memory_web._tempo_add("kurz/freizeitgluecklich", 1.35)  # second try wins
    items = memory_web._tempo_read()
    assert [i["name"] for i in items] == ["nacht/tanz14", "kurz/freizeitgluecklich"]
    assert items[-1]["rate"] == 1.35
