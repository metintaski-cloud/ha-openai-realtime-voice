"""Leyla's two memory lists mirrored to Home Assistant to-do lists."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import memory, todo_sync  # noqa: E402


def test_merge():
    assert todo_sync.merge(["A", "B"], [], None) == ["A", "B"]
    assert todo_sync.merge(["A", "B"], ["A", "B", "C"], ["A", "B"]) == ["A", "B", "C"]
    assert todo_sync.merge(["A", "B"], ["A"], ["A", "B"]) == ["A"]           # deleted in app
    assert todo_sync.merge(["A", "B", "D"], ["A", "B"], ["A", "B"]) == ["A", "B", "D"]  # learned
    assert todo_sync.merge(["A", "D"], ["B", "C"], ["A", "B"]) == ["D", "C"]  # both changed


class FakeHA:
    def __init__(self):
        self.lists = {"todo.leyla_familie": [], "todo.leyla_freunde_und_verwandte": [],
                      "todo.leyla_privat": []}
        self.n = 0

    def items(self, entity):
        return [dict(i) for i in self.lists[entity]]

    def add(self, entity, summary, status="needs_action"):
        self.n += 1
        self.lists[entity].append({"uid": str(self.n), "summary": summary, "status": status})

    def remove(self, entity, uids):
        self.lists[entity] = [i for i in self.lists[entity] if i["uid"] not in uids]


def _sync(tmp_path, ha):
    store = memory.MemoryStore(str(tmp_path / "memory.json"))
    sync = todo_sync.TodoSync(store, api_url="http://x/api", token="t",
                              state_path=str(tmp_path / "state.json"))

    async def call(client, service, data, response=False):
        e = data["entity_id"]
        if service == "get_items":
            return {"service_response": {e: {"items": ha.items(e)}}}
        if service == "add_item":
            ha.add(e, data["item"])
        if service == "remove_item":
            ha.remove(e, data["item"])
        if service == "update_item":
            for i in ha.lists[e]:
                if i["uid"] == data["item"]:
                    i["status"] = data["status"]
        return {}

    sync._call = call
    return store, sync


async def test_sync_both_ways(tmp_path):
    ha = FakeHA()
    store, sync = _sync(tmp_path, ha)
    store.save_all({"family": ["Person: Umut (Metins Bruder)."], "private": ["Geheim 1"]})
    await sync.sync_once()   # first run: Leyla's entries appear in the app
    assert [i["summary"] for i in ha.items("todo.leyla_privat")] == ["Geheim 1"]
    assert [i["summary"] for i in ha.items("todo.leyla_familie")] == ["Person: Umut (Metins Bruder)."]

    # A tap ticks the private entry off by accident: it stays and is unticked again
    ha.lists["todo.leyla_privat"][0]["status"] = "completed"
    await sync.sync_once()
    assert store.load(memory.PRIVATE) == ["Geheim 1"]
    assert ha.items("todo.leyla_privat")[0]["status"] == "needs_action"

    # Metin deletes the private entry and adds a family entry in the app
    ha.remove("todo.leyla_privat", [ha.items("todo.leyla_privat")[0]["uid"]])
    ha.add("todo.leyla_familie", "Person: Ayşe (Metins Schwester).")
    await sync.sync_once()
    assert store.load(memory.PRIVATE) == []
    assert store.load(memory.FAMILY) == ["Person: Umut (Metins Bruder).",
                                         "Person: Ayşe (Metins Schwester)."]
    assert ha.items("todo.leyla_privat") == []

    # Leyla learns something: it shows up in the app
    store.save(store.load() + ["Aktuell bis 20.11.2026: Ayşe ist erkältet."])
    await sync.sync_once()
    assert len(ha.items("todo.leyla_familie")) == 3

    # A restart keeps the agreed state: a deletion in the app is not undone
    ha.remove("todo.leyla_familie", [ha.items("todo.leyla_familie")[0]["uid"]])
    store2, sync2 = _sync(tmp_path, ha)
    await sync2.sync_once()
    assert "Person: Umut (Metins Bruder)." not in store2.load()


async def test_renamed_in_app(tmp_path):
    ha = FakeHA()
    store, sync = _sync(tmp_path, ha)
    store.save_all({"family": ["Person: Ayse (Metins Schwester)."], "private": []})
    await sync.sync_once()
    ha.lists["todo.leyla_familie"][0]["summary"] = "Person: Ayşe (Metins Schwester)."
    await sync.sync_once()
    assert store.load() == ["Person: Ayşe (Metins Schwester)."]
    assert [i["summary"] for i in ha.items("todo.leyla_familie")] == [
        "Person: Ayşe (Metins Schwester)."]
