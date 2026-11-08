"""
Mirror Leyla's two memory lists to two to-do lists in Home Assistant, so Metin can read
and edit them in the Home Assistant app (no code phrase needed there):

  todo.leyla_familie   the open family list
  todo.leyla_privat    Metin's private list

Both directions every SYNC_INTERVAL_S (and right after Leyla saved something):
an entry deleted in the app is forgotten, an entry added or renamed in the app is
remembered, and what Leyla learned shows up in the app. Ticking an entry off does not
forget it (a tap in the app or the widget ticks it off by accident); it is unticked
again on the next sync. The last list both sides agreed
on decides who changed what, so edits on both sides are merged.
"""
import asyncio
import json
import logging
import os
from typing import Optional

import httpx

from app import memory

logger = logging.getLogger(__name__)

SYNC_INTERVAL_S = 30.0
DEFAULT_LISTS = {memory.FAMILY: "todo.leyla_familie", memory.PRIVATE: "todo.leyla_privat"}


def merge(store: list[str], ha: list[str], last: Optional[list[str]]) -> list[str]:
    """Combine Leyla's list and the app's list since they last agreed."""
    if last is None:  # first run: keep everything from both sides
        return store + [x for x in ha if x not in store]
    removed = [x for x in last if x not in ha]
    added = [x for x in ha if x not in last and x not in store]
    return [x for x in store if x not in removed] + added


class TodoSync:
    def __init__(self, store: memory.MemoryStore, api_url: Optional[str] = None,
                 token: Optional[str] = None, lists: Optional[dict] = None,
                 state_path: Optional[str] = None) -> None:
        self.store = store
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self.lists = dict(lists or DEFAULT_LISTS)
        self.state_path = state_path
        self._last: dict = {k: None for k in self.lists}
        if state_path:
            try:
                with open(state_path, encoding="utf-8") as f:
                    saved = json.load(f)
                self._last.update({k: v for k, v in saved.items() if k in self.lists})
            except (OSError, ValueError):
                pass
        self._wake = asyncio.Event()
        self._missing_logged: set = set()

    @property
    def available(self) -> bool:
        return bool(self.token)

    def kick(self) -> None:
        self._wake.set()

    async def _call(self, client: httpx.AsyncClient, service: str, data: dict,
                    response: bool = False) -> dict:
        url = f"{self.api_url}/services/todo/{service}" + ("?return_response" if response else "")
        resp = await client.post(url, json=data,
                                 headers={"Authorization": f"Bearer {self.token}"})
        resp.raise_for_status()
        return resp.json() if response else {}

    async def items(self, client: httpx.AsyncClient, entity: str) -> Optional[list[dict]]:
        """All items of a to-do list, None when the list does not exist."""
        try:
            data = await self._call(client, "get_items", {"entity_id": entity}, response=True)
        except httpx.HTTPStatusError as e:
            if entity not in self._missing_logged:
                self._missing_logged.add(entity)
                logger.info("To-do list %s not available (%s)", entity, e.response.status_code)
            return None
        return ((data.get("service_response") or {}).get(entity) or {}).get("items") or []

    async def sync_once(self) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            lists = self.store.load_all()
            changed = False
            for kind, entity in self.lists.items():
                items = await self.items(client, entity)
                if items is None:
                    continue
                ha = []
                for i in items:
                    x = " ".join((i.get("summary") or "").split())
                    if x and x not in ha:
                        ha.append(x)
                mine = lists[kind]
                merged = merge(mine, ha, self._last[kind])
                if merged != mine:
                    lists[kind] = merged
                    changed = True
                    logger.info("Memory %s: %d entries changed in the Home Assistant app",
                                kind, abs(len(merged) - len(mine)) or 1)
                # Bring the app list in line: untick, drop removed ones, add new ones
                stale = [i["uid"] for i in items if i.get("uid")
                         and " ".join((i.get("summary") or "").split()) not in merged]
                if stale:
                    await self._call(client, "remove_item", {"entity_id": entity, "item": stale})
                for i in items:
                    if i.get("status") == "completed" and i.get("uid") not in stale:
                        await self._call(client, "update_item", {
                            "entity_id": entity, "item": i["uid"], "status": "needs_action"})
                for x in merged:
                    if x not in ha:
                        await self._call(client, "add_item", {"entity_id": entity, "item": x})
                self._last[kind] = list(merged)
            if changed:
                self.store.save_all(lists)
            if self.state_path:
                try:
                    with open(self.state_path, "w", encoding="utf-8") as f:
                        json.dump(self._last, f, ensure_ascii=False)
                except OSError as e:
                    logger.warning("Could not save the to-do sync state: %s", e)

    async def run(self) -> None:
        if not self.available:
            return
        logger.info("Memory lists mirrored to %s", ", ".join(self.lists.values()))
        while True:
            try:
                await self.sync_once()
            except Exception as e:
                logger.warning("To-do sync failed: %s", e)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), SYNC_INTERVAL_S)
                await asyncio.sleep(1.0)
            except asyncio.TimeoutError:
                pass
