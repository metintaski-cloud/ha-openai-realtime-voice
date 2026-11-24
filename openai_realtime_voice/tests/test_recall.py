"""What comes to her mind by itself (app/recall.py). The sentences here are invented and
neutral on purpose: nothing from the real diary ever goes into the repository."""
import asyncio
import json

from app import chat, diary, recall

NOW = 2_000_000_000.0
DAY = diary.DAY
TOPICS = {"garten": 0, "rosen": 0, "beet": 0, "pflanzen": 0, "auto": 1, "werkstatt": 1,
          "reifen": 1, "urlaub": 2, "meer": 2, "strand": 2, "kuchen": 3, "backen": 3}


def fake_vec(text):
    """A stand in for the meaning model: one axis per topic, a little noise axis per text."""
    v = [0.0] * recall.DIMS
    for word, axis in TOPICS.items():
        if word in text.lower():
            v[axis] += 1.0
    v[10 + len(text) % 50] += 0.2
    return recall._unit(v)


def make(tmp_path, monkeypatch, key="k"):
    dy = diary.Diary(str(tmp_path / "d.json"))
    ix = recall.Index(dy, key, path=str(tmp_path / "r.json"))
    calls = []

    async def embed(texts, timeout=30.0, model="", dims=0):
        calls.append(list(texts))
        return [fake_vec(t) for t in texts]
    monkeypatch.setattr(ix, "embed", embed)
    return dy, ix, calls


def entry(text, privat=False):
    return {"wichtig": True, "lang": text, "mittel": text[:160], "kurz": text[:70], "privat": privat}


def test_old_entry_comes_to_mind_though_it_left_the_window(tmp_path, monkeypatch):
    dy, ix, calls = make(tmp_path, monkeypatch)
    dy.add(entry("Wir sprachen über den Garten und die Rosen am Zaun."), "Metin", "chat", now=NOW - 20 * DAY)
    dy.add(entry("Das Auto war in der Werkstatt, neue Reifen."), "Metin", "chat", now=NOW - 19 * DAY)

    async def run():
        assert await ix.sync() == 2 and await ix.sync() == 0   # only new entries cost a call
        note = await ix.note("Was machen eigentlich deine Pflanzen im Beet?", "Metin", now=NOW)
        assert "Rosen am Zaun" in note and "Werkstatt" not in note
        assert "FÄLLT DIR GERADE DAZU EIN" in note and "vor etwa 3 Wochen (im Chat)" in note
        assert await ix.note("Wie spät ist es?", "Metin", now=NOW) == ""   # nothing fits: no note
    asyncio.run(run())
    assert len(calls[0]) == 2


def test_private_and_other_peoples_entries_are_no_candidates(tmp_path, monkeypatch):
    dy, ix, _ = make(tmp_path, monkeypatch)
    dy.add(entry("Im Urlaub am Meer waren wir uns sehr nah.", privat=True), "Metin", "chat", now=NOW - 9 * DAY)
    dy.add(entry("Mama erzählte vom Urlaub am Strand."), "Gülfikar Taskiran", "stimme", now=NOW - 8 * DAY)
    dy.add(entry("Jemand fragte nach dem Meer."), "", "stimme", now=NOW - 40 * DAY)

    async def run():
        await ix.sync()
        open_ = [e["lang"] for _, e in await ix.find("Urlaub am Meer", "Metin", private=False)]
        assert open_ == ["Jemand fragte nach dem Meer."]
        mine = [e["lang"] for _, e in await ix.find("Urlaub am Meer", "Metin", private=True)]
        assert "Im Urlaub am Meer waren wir uns sehr nah." in mine
        assert not any("Mama" in t for t in mine)
        guest = [e["lang"] for _, e in await ix.find("Urlaub am Meer", "", private=False)]
        assert guest == ["Jemand fragte nach dem Meer."]
    asyncio.run(run())


def test_what_she_has_before_her_is_not_repeated_and_twins_show_once(tmp_path, monkeypatch):
    dy, ix, _ = make(tmp_path, monkeypatch)
    dy.add(entry("Heute haben wir Kuchen gebacken, Backen macht Spaß."), "Metin", "chat", now=NOW - 3600)
    dy.add(entry("Kuchen backen mit Zimt, das war schön."), "Metin", "chat", now=NOW - 20 * DAY)
    dy.add(entry("Kuchen backen mit Zimt, das war schön!"), "Metin", "chat", now=NOW - 20 * DAY + 60)

    async def run():
        await ix.sync()
        note = await ix.note("Sollen wir wieder Kuchen backen?", "Metin", now=NOW)
        assert "gebacken" not in note            # today's entry is in her diary window already
        assert note.count("mit Zimt") == 1       # two entries saying the same: one is enough
    asyncio.run(run())


def test_deleted_entries_lose_their_vector_and_changed_text_gets_a_new_one(tmp_path, monkeypatch):
    dy, ix, calls = make(tmp_path, monkeypatch)
    dy.add(entry("Der Garten blüht."), "Metin", "chat", now=NOW - 5 * DAY)
    dy.touched(["gesicht"], now=NOW - 2 * DAY)

    async def run():
        await ix.sync()
        assert len(ix.vectors) == 2
        dy.touched(["bauch"], now=NOW - 2 * DAY + 60)      # the day's line is rewritten
        assert await ix.sync() == 1
        dy.delete([NOW - 5 * DAY])
        await ix.sync()
        assert len(ix.vectors) == 1
    asyncio.run(run())
    again = recall.Index(dy, "k", path=str(tmp_path / "r.json"))   # the file holds the vectors
    assert len(again.vectors) == 1


def test_without_a_key_or_an_answer_nothing_breaks(tmp_path, monkeypatch):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.add(entry("Umut zieht nach Izmir."), "Metin", "chat", now=NOW - 60 * DAY)
    off = recall.Index(dy, "", path=str(tmp_path / "r.json"))

    async def run():
        assert await off.sync() == 0 and await off.note("Izmir", "Metin") == ""
        assert "Izmir" in await off.ask("Umut Izmir", "Metin")     # the word search still works
        assert "nichts" in await off.ask("Fahrrad", "Metin")
        on = recall.Index(dy, "k", path=str(tmp_path / "r2.json"), url="http://127.0.0.1:9/none")
        assert await on.sync() == 0 and await on.note("Izmir", "Metin") == ""
    asyncio.run(run())


def test_asking_on_purpose_is_wider_and_adds_the_word_search(tmp_path, monkeypatch):
    dy, ix, _ = make(tmp_path, monkeypatch)
    dy.add(entry("Wir planen den Urlaub am Meer."), "Metin", "chat", now=NOW - 50 * DAY)
    dy.add(entry("Umut zieht nach Izmir."), "Metin", "chat", now=NOW - 60 * DAY)

    async def run():
        await ix.sync()
        text = await ix.ask("Strand und Izmir", "Metin")
        assert "Urlaub am Meer" in text and "Izmir" in text
    asyncio.run(run())


def test_settings_are_kept_and_measuring_gives_numbers_only(tmp_path, monkeypatch):
    dy, ix, _ = make(tmp_path, monkeypatch)
    dy.add(entry("Wir sprachen über den Garten und die Rosen."), "Metin", "chat", now=NOW - 20 * DAY)
    dy.add(entry("Neue Reifen für das Auto."), "Metin", "chat", now=NOW - 3600)

    async def run():
        await ix.sync()
        assert (await ix.api("/api/kopf/settings", {"settings": {"top": 2, "min_sim": 0.5, "x": 1}}))[
            "settings"]["top"] == 2
        assert (await ix.api("/api/kopf/cases", {"cases": [
            {"q": "Pflanzen im Beet", "t": NOW - 20 * DAY},
            {"q": "Auto Reifen", "t": [NOW - 3600]}, {"nix": 1}]}))["cases"] == 2
        out = await ix.measure(now=NOW)
        assert out["cases"] == 2 and out["old_window"] == 1 and out["new_mind"] == 2
        assert out["new_total"] == 2 and out["rows"][0]["rank"] == 1
        assert "Garten" not in json.dumps(out, ensure_ascii=False)     # never a text
        status = await ix.api("/api/kopf/status", {})
        assert status["vectors"] == 2 and status["cases"] == 2
    asyncio.run(run())
    assert recall.Index(dy, "k", path=str(tmp_path / "r.json")).settings["min_sim"] == 0.5


def test_a_short_message_is_searched_with_her_last_words():
    history = [{"role": "user", "text": "Hallo"}, {"role": "leyla", "text": "Wie war es im Garten?"}]
    assert recall.query_text("Und dann?", history) == "Wie war es im Garten?\nUnd dann?"
    assert recall.query_text("Ich war heute lange im Garten", history) == "Ich war heute lange im Garten"
    assert recall.query_text(chat.touch_message("gesicht"), history) == ""
    assert recall.query_text("  ", history) == ""


def test_the_touch_zone_is_read_back_from_the_stage_note():
    assert chat.touch_zone(chat.touch_message("bauch")) == "bauch"
    assert chat.touch_zone("Ich berühre dich") == "" and chat.touch_zone("") == ""


def test_embed_talks_to_the_service_in_its_format(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.headers["Authorization"], body))
            rows = [{"index": i, "embedding": [float(i + 1)] + [0.0] * (recall.DIMS - 1)}
                    for i in range(len(body["input"]))]
            data = json.dumps({"data": rows[::-1], "usage": {"total_tokens": 7}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ix = recall.Index(diary.Diary(str(tmp_path / "d.json")), "key", path=str(tmp_path / "r.json"),
                          url=f"http://127.0.0.1:{server.server_address[1]}/v1/embeddings")
        vecs = asyncio.run(ix.embed(["eins", "zwei"]))
    finally:
        server.shutdown()
    auth, body = seen[0]
    assert auth == "Bearer key" and body == {"model": recall.MODEL, "input": ["eins", "zwei"],
                                             "dimensions": recall.DIMS}
    assert len(vecs) == 2 and abs(vecs[1][0] - 1.0) < 1e-6 and len(vecs[0]) == recall.DIMS


def test_a_word_bonus_brings_the_entry_that_holds_the_name(tmp_path, monkeypatch):
    dy, ix, _ = make(tmp_path, monkeypatch)
    dy.add(entry("Im Garten blühen die Rosen."), "Metin", "chat", now=NOW - 20 * DAY)
    dy.add(entry("Onkel Kemal kommt bald zu Besuch."), "Metin", "chat", now=NOW - 21 * DAY)

    async def run():
        await ix.sync()
        q = "Wann kommt Kemal in den Garten?"
        plain = [e["lang"] for _, e in await ix.find(q, "Metin")]
        ix.set({"word_bonus": 1.0})
        lifted = [e["lang"] for _, e in await ix.find(q, "Metin")]
        assert not any("Kemal" in t for t in plain) and any("Kemal" in t for t in lifted)
    asyncio.run(run())


def test_everyday_messages_count_as_noise_and_models_are_compared_in_memory(tmp_path, monkeypatch):
    dy, ix, calls = make(tmp_path, monkeypatch)
    dy.add(entry("Wir sprachen über den Garten und die Rosen."), "Metin", "chat", now=NOW - 20 * DAY)
    dy.add(entry("Neue Reifen für das Auto."), "Metin", "chat", now=NOW - 19 * DAY)

    async def run():
        await ix.sync()
        ix.set_cases([{"q": "Pflanzen im Beet", "t": NOW - 20 * DAY}, {"q": "Guten Morgen"}])
        out = await ix.measure(now=NOW)
        assert out["cases"] == 1 and out["new_mind"] == 1 and out["top1"] == 1
        assert out["noise"] == 1 and out["noise_shown"] == 0 and len(out["noise_best"]) == 1
        before = dict(ix.vectors)
        started = await ix.api("/api/kopf/compare", {"start": True})
        assert started["running"]
        await ix._comparing
        done = await ix.api("/api/kopf/compare", {})
        assert not done["running"] and len(done["results"]) == len(recall.COMPARE) * len(recall.BONUSES)
        assert all(r["ok"] and r["top4"] == 1 and "rows" not in r for r in done["results"])
        assert ix.vectors == before                      # the index itself is not touched
    asyncio.run(run())


def test_another_model_or_size_makes_every_vector_again(tmp_path, monkeypatch):
    dy, ix, calls = make(tmp_path, monkeypatch)
    dy.add(entry("Der Garten blüht."), "Metin", "chat", now=NOW - 5 * DAY)

    async def run():
        await ix.sync()
        out = ix.set({"model": "text-embedding-3-large", "dims": 99999, "min_sim": 0.4})
        assert out["model"] == "text-embedding-3-large" and out["dims"] == 3072
        assert ix.vectors == {}
        await ix._syncing
        assert len(ix.vectors) == 1
        assert ix.set({"model": "irgendwas"})["model"] == "text-embedding-3-large"
    asyncio.run(run())
