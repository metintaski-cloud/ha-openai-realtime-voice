"""Order in her memory (app/ordnung.py): rules about switching devices never enter a list as free text."""
import pytest

from app import chat, memory, ordnung

RULES = [  # the three texts of Metin's photo of 28 Nov 2026 and a few of the same kind
    "Wenn jemand „Lambaları kapat“ sagt, schaltet Leyla das Ventilatorlicht und die Stehlampen 3 und 4 aus; 1 und 2 bleiben an.",
    "Die Stehlampen 1 und 2 gehören zu Leyla und gehen beim Einschlafen mit aus.",
    "Bei der Aufforderung, alle Lichter auszuschalten, gehört auch das Ventilatorlicht dazu.",
    "Wenn Metin 'Bay bay' sagt, macht Leyla alle Lampen aus.",
    "Bei „gute Nacht“ wird der Fernseher immer ausgeschaltet.",
    "Lambaları kapat denince Leyla ışıkları kapatır.",
    "Wenn Anne ins Bett geht, bleibt die Stehlampe 4 an.",
]
FACTS = [  # knowledge about people and the home: must stay
    "Person: Metin | Zugehörigkeit: Sohn | Arbeit: Elektroniker | Sonst: sagt oft, wenn das Licht ausgeschaltet werden soll",
    "Metin schaut abends gern fern, der Fernseher läuft oft nebenbei.",
    "Gülfikar mag es, wenn das Licht abends warm ist.",
    "Metin hat die neue Lampe im Flur selbst montiert.",
    "Metin geht gern an den Rhein, wenn das Licht schön ist.",
    "Aktuell bis 30.11.2026: Leyla plant mit Metin einen gemütlichen Filmabend.",
    "Im Wohnzimmer stehen vier Stehlampen und ein Deckenventilator.",
    "Umut sagt immer, dass er zu wenig schläft.",
    "",
]


@pytest.mark.parametrize("text", RULES)
def test_a_switching_rule_is_recognised(text):
    assert ordnung.is_switch_rule(text)


@pytest.mark.parametrize("text", FACTS)
def test_knowledge_about_people_and_the_home_is_not_a_switching_rule(text):
    assert not ordnung.is_switch_rule(text)


def test_the_memory_update_cannot_add_or_rewrite_switching_rules_and_never_drops_a_stored_one():
    old = {"family": [FACTS[1], RULES[1]], "friends": [], "leyla": [FACTS[6]], "private": []}
    new = {"family": [FACTS[1], RULES[1].replace("1 und 2", "3 und 4"), RULES[0], FACTS[3]],   # rewritten, added
           "friends": [RULES[3]], "leyla": [], "private": [FACTS[2]]}
    out, dropped, back = ordnung.keep_switch_rules_out(old, new, ("family", "friends", "private", "leyla"))
    assert out["family"] == [FACTS[1], FACTS[3], RULES[1]]      # the new fact stays, the stored rule is as it was
    assert out["friends"] == [] and out["private"] == [FACTS[2]]
    assert out["leyla"] == []                                    # other guards decide about a dropped fact, not this one
    assert (dropped, back) == (3, 1)
    same, d, b = ordnung.keep_switch_rules_out(old, old, ("family", "friends", "private", "leyla"))
    assert same == old and (d, b) == (0, 0)                      # nothing to do: nothing changes


def test_the_chat_cannot_propose_a_switching_rule():
    lists = {"family": [FACTS[1], RULES[1]], "friends": [], "leyla": [], "private": []}
    raw = [{"action": "add", "kind": "family", "new": RULES[0]},
           {"action": "edit", "kind": "family", "old": FACTS[1], "new": RULES[3]},
           {"action": "add", "kind": "family", "new": FACTS[3]},
           {"action": "delete", "kind": "family", "old": RULES[1]}]          # deleting one stays possible: he says yes or no
    got = chat.valid_proposals(raw, lists)
    assert [(p["action"], p.get("new") or p.get("old")) for p in got] == [("add", FACTS[3]), ("delete", RULES[1])]


def test_the_prompt_of_the_memory_update_says_it_too():
    assert "Regeln zum Schalten von Geräten" in memory.SUMMARY_PROMPT and "feste Befehle" in memory.SUMMARY_PROMPT


def test_the_page_of_fixed_commands_lists_and_deletes_only_with_the_code_word(tmp_path, monkeypatch):
    import asyncio
    import json

    from app import befehle, memory_web
    monkeypatch.setitem(memory_web._code_fails, "n", 0)
    cmds = befehle.Commands(path=str(tmp_path / "befehle.json"))
    monkeypatch.setattr(befehle.Commands, "lamp_count", 4, raising=False)
    assert cmds.define({"name": "Gute Nacht", "saetze": ["Gute Nacht", "İyi geceler"], "lampen_aus": [1, 2, 3, 4],
                        "ventilatorlicht": "aus"}).get("ok")
    assert cmds.define({"name": "Kino", "saetze": ["Kino"], "lampen_aus": [3, 4]}).get("ok")
    store = memory_web.memory.MemoryStore(str(tmp_path / "m.json")) if hasattr(memory_web, "memory") else None

    async def ask(body):
        server = await memory_web.start_http(store, None, host="127.0.0.1", port=0, code_phrase="Leyla Sonne Mond", befehle=cmds)
        port = server.sockets[0].getsockname()[1]
        raw = json.dumps(body).encode()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"POST /api/befehle HTTP/1.1\r\nContent-Length: %d\r\n\r\n" % len(raw) + raw)
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return json.loads(data.split(b"\r\n\r\n", 1)[1])

    assert asyncio.run(ask({})) == {"ok": False}                                  # no code word: nothing
    assert asyncio.run(ask({"loeschen": "Kino"})) == {"ok": False} and len(cmds.listing()) == 2
    out = asyncio.run(ask({"code": "Sonne Mond"}))
    assert out["ok"] and [c["name"] for c in out["items"]] == ["Gute Nacht", "Kino"]
    assert out["items"][0]["saetze"] == ["Gute Nacht", "İyi geceler"] and "Ventilatorlicht aus" in out["items"][0]["tut"]
    out = asyncio.run(ask({"code": "Sonne Mond", "loeschen": "Kino"}))
    assert out["ok"] and [c["name"] for c in out["items"]] == ["Gute Nacht"] and len(cmds.listing()) == 1
    assert asyncio.run(ask({"code": "Sonne Mond", "loeschen": "gibt es nicht"}))["ok"] is False
    assert "function openBefehle" in memory_web.PAGE and "'befehle','Feste Befehle'" in memory_web.PAGE
