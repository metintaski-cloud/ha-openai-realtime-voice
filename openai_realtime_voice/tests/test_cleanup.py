"""Metin is the filter: the review only proposes, deleting needs his numbers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import cleanup, memory  # noqa: E402


def make(tmp_path, entries, picks):
    store = memory.MemoryStore(str(tmp_path / "memory.json"))
    store.save_all(entries)
    pushed = []

    async def notify(title, message):
        pushed.append((title, message))

    c = cleanup.Cleaner(store, "k", ["m"], notify=notify)

    async def ask(self_entries):
        c.asked = self_entries
        return picks
    c._ask = ask
    return store, c, pushed


async def test_review_proposes_but_deletes_nothing(tmp_path):
    store, c, pushed = make(
        tmp_path,
        {"family": ["Person: Anne | Spricht: Türkisch", "Eiffelturm ist 330 m hoch"],
         "friends": [], "private": []},
        [{"nummer": 1, "grund": "Wissensfrage"}, {"nummer": 99, "grund": "gibt es nicht"}])
    r = await c.review()
    assert r["neu"] == 1
    assert store.load("family") == ["Person: Anne | Spricht: Türkisch", "Eiffelturm ist 330 m hoch"]
    assert "Eiffelturm" in pushed[0][1] and "Gelöscht wird nichts" in pushed[0][1]
    assert all(not f.startswith("Person:") for _, f in c.asked)  # profiles are never offered


async def test_delete_only_the_named_numbers(tmp_path):
    store, c, _ = make(tmp_path, {"family": ["a", "b", "c"], "friends": [], "private": []},
                       [{"nummer": 1, "grund": "x"}, {"nummer": 2, "grund": "y"},
                        {"nummer": 3, "grund": "z"}])
    await c.review()
    assert c.delete("2") == {"gestrichen": 1, "offen": 2}
    assert store.load("family") == ["a", "c"]


async def test_kept_entries_are_never_proposed_again(tmp_path):
    store, c, _ = make(tmp_path, {"family": ["a", "b"], "friends": [], "private": []},
                       [{"nummer": 1, "grund": "x"}])
    await c.review()
    assert c.keep(None)["behalten"] == 1
    await c.review()
    assert [f for _, f in c.asked] == ["b"]
    assert store.load("family") == ["a", "b"]


def test_parse_numbers():
    assert cleanup.parse_numbers("1, 3", 3) == [0, 2]
    assert cleanup.parse_numbers(None, 2) == [0, 1]
    assert cleanup.parse_numbers("9", 2) == []


async def test_decide_deletes_and_keeps_on_the_same_numbering(tmp_path):
    store, c, _ = make(tmp_path, {"family": ["a", "b", "c"], "friends": [], "private": []},
                       [{"nummer": 1, "grund": "x"}, {"nummer": 2, "grund": "y"},
                        {"nummer": 3, "grund": "z"}])
    await c.review()
    assert c.decide("1,2", "3") == {"gestrichen": 2, "behalten": 1, "offen": 0}
    assert store.load("family") == ["c"]
    assert "error" in c.decide("", "")


def test_chat_cleanup_helpers():
    from app import chat
    assert chat.cleanup_numbers({"streichen": [1, 2], "behalten": 3}) == ("1,2", "3")
    assert chat.cleanup_numbers(None) == ("", "")
    assert chat.cleanup_note({"offen": 0}) == ""
    note = chat.cleanup_note({"vorschlaege": [{"nummer": 1, "liste": "family", "eintrag": "x", "grund": "doppelt"}]})
    assert "1. (family) x: doppelt" in note and "aufraeumen" in note
