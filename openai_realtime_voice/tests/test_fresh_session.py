"""A fresh GPT Live session in a running talk (2.155.0): the connection behind the talk is
exchanged, nothing of the talk is lost, and when it does not work the notes go out as before."""
import asyncio
import json
import time
import types

import websockets
import websockets.exceptions

from app import live_link, talk_notes


class Conn:
    """A stand in for a GPT Live connection: events to read, a record of what was sent."""
    def __init__(self, name, events=()):
        self.name, self.sent, self.closed = name, [], False
        self.queue = asyncio.Queue()
        for e in events:
            self.queue.put_nowait(e)

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def recv(self):
        item = await self.queue.get()
        if item is None:
            raise websockets.exceptions.ConnectionClosedOK(None, None)
        return item if isinstance(item, str) else json.dumps(item)

    async def close(self):
        self.closed = True
        self.queue.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except websockets.exceptions.ConnectionClosedOK:
            raise StopAsyncIteration


def test_the_line_reads_on_from_the_new_connection_and_drops_what_the_old_one_still_says():
    async def go():
        old, new = Conn("old"), Conn("new")
        line = live_link.LiveLine(old)
        got = []

        async def read():
            async for raw in line:
                got.append(raw)
        task = asyncio.create_task(read())
        old.queue.put_nowait("a")
        await asyncio.sleep(0.01)
        assert line.swap(new) is old and line.swaps == 1
        old.queue.put_nowait("late")          # of the old session: dropped
        await old.close()
        new.queue.put_nowait("b")
        await asyncio.sleep(0.01)
        await line.send(json.dumps({"x": 1}))  # sending goes to the new one
        assert new.sent == [{"x": 1}] and old.sent == []
        await new.close()                      # the talk's own connection ends: reading ends
        await asyncio.wait_for(task, 1)
        return got
    assert asyncio.run(go()) == ["a", "b"]


def test_the_history_keeps_the_last_turns_within_its_room():
    h = talk_notes.TalkNotesMixin._history([("bot", "Hallo"), ("user", " Ich   bin es "), ("bot", "")])
    assert [m["role"] for m in h] == ["assistant", "user"]
    assert h[0]["content"][0] == {"type": "output_text", "text": "Hallo"}
    assert h[1]["content"][0] == {"type": "input_text", "text": "Ich bin es"}
    long = [("user", "x" * 2000)] * 10
    assert sum(len(m["content"][0]["text"]) for m in talk_notes.TalkNotesMixin._history(long)) <= talk_notes.HISTORY_MAX_CHARS


class Home(talk_notes.TalkNotesMixin):
    def __init__(self, new_conn=None, frisch=1):
        self.recall = types.SimpleNamespace(settings={"frisch": frisch})
        self._background = set()
        self.new_conn, self.sent_items, self.payloads = new_conn, [], []

    async def _take_live(self):
        if self.new_conn is None:
            raise RuntimeError("no connection")
        return self.new_conn, True

    def _session_start(self, extra, start, history=None, stage=False):
        self.payloads.append((extra, start[0], history))
        start[1]["start_held"] = {}
        return {"session": {"instructions": "rules", "input": history}}

    def _in_background(self, coro):
        task = asyncio.ensure_future(coro)
        self._background.add(task)

    async def _close_quietly(self, ws):
        await ws.close()

    async def _send_items(self, live_ws, state, items):
        self.sent_items.append(items)


def quiet_state(**more):
    return dict({"dialog": [("user", "Leyla habibi"), ("bot", "Habibi!")], "last_audio_time": 0.0,
                 "last_voice_at": 0.0, "context_extra": "ctx"}, **more)


def test_a_fresh_session_takes_the_place_once_nothing_is_in_the_air(monkeypatch):
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.1)

    async def go():
        old, new = Conn("old"), Conn("new", [{"type": "session.started"}])
        line, home, state = live_link.LiveLine(old), Home(new), quiet_state()
        state["last_audio_time"] = time.monotonic()          # she is still answering: wait
        home._start_fresh(line, state, [("private", "P"), ("unlock", "U"), ("diary", "D")], ["fallback"])
        await asyncio.sleep(0.25)
        assert line.ws is old and len(home.payloads) == 1    # started already, not yet in place
        assert line.standby is new                           # and it listens along
        state["last_audio_time"] = time.monotonic() - 1.0    # she is done
        await asyncio.wait_for(state["fresh_task"], 3)
        await asyncio.sleep(0.01)
        return old, new, line, home, state
    old, new, line, home, state = asyncio.run(go())
    assert line.ws is new and old.closed and state["fresh_done"] == 1 and not home.sent_items
    extra, items, history = home.payloads[0]
    assert extra == "ctx" and [k for k, _ in items] == ["unlock", "diary", "private"]   # in her order
    assert [m["role"] for m in history] == ["user", "assistant"] and new.sent[0]["session"]["input"] == history


AUDIO = json.dumps({"type": "session.input_audio.append", "audio": "AAAA"})


def test_she_is_never_cut_off_however_long_she_talks(monkeypatch):
    """24 Nov 2026, 13:50 at home: the exchange came as she began to answer and her sentence
    broke off; the room is never quiet there (TV), so the microphone level is no sign."""
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_QUIET_S", 0.1)
    monkeypatch.setattr(talk_notes, "FRESH_HEAR_S", 0.05)

    async def go():
        old, new = Conn("old"), Conn("new", [{"type": "session.started"}])
        line, home, state = live_link.LiveLine(old), Home(new), quiet_state()
        stop = []

        async def room():   # the TV keeps the microphone loud all the time; she talks until told
            while not stop:
                state["last_voice_at"] = time.monotonic()
                if "her_done" not in state:
                    state["last_audio_time"] = time.monotonic()
                await asyncio.sleep(0.02)
        noise = asyncio.ensure_future(room())
        home._start_fresh(line, state, [("unlock", "U")], ["fallback"])
        await asyncio.sleep(0.6)
        still_old = line.ws is old                             # she is speaking: nothing is exchanged
        state["her_done"] = True
        await asyncio.wait_for(state["fresh_task"], 3)
        stop.append(1)
        await noise
        return still_old, line.ws is new
    assert asyncio.run(go()) == (True, True)


def test_the_new_session_listens_along_so_his_first_words_are_not_lost(monkeypatch):
    """24 Nov 2026, 14:03 at home: he asked right after her short reply, the exchange fell
    into his first words and the new session asked him to finish his sentence."""
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_QUIET_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_HEAR_S", 0.05)

    async def go():
        old, new = Conn("old"), Conn("new", [{"type": "session.started"}])
        line, home, state = live_link.LiveLine(old), Home(new), quiet_state()
        state["last_audio_time"] = time.monotonic() + 0.4      # she is still giving her short reply
        home._start_fresh(line, state, [("unlock", "U")], ["fallback"])
        await asyncio.sleep(0.15)                              # the new session is ready, not in place
        assert line.ws is old and line.standby is new
        await line.send(AUDIO)                                 # he begins to speak: both hear it
        await line.send(json.dumps({"type": "session.commentary.append", "content": "x"}))  # a note: only the running one
        new.queue.put_nowait({"type": "session.output_audio.delta", "delta": "AAAA"})    # it says something too early
        await asyncio.wait_for(state["fresh_task"], 3)
        await line.send(AUDIO)                                 # after the exchange: only the new one
        await asyncio.sleep(0.01)
        return old, new, line
    old, new, line = asyncio.run(go())
    audio = lambda c: [m for m in c.sent if m.get("type") == "session.input_audio.append"]
    assert len(audio(old)) == 1 and len(audio(new)) == 2       # nothing of his sentence is missing
    assert [m["type"] for m in old.sent if m["type"] != "session.input_audio.append"] == ["session.commentary.append"]
    assert not any(m.get("type") == "session.commentary.append" for m in new.sent)
    assert line.ws is new and line.standby is None and new.queue.empty()   # what it said too early is gone


def test_a_session_that_breaks_while_it_listens_along_does_not_disturb_the_talk():
    async def go():
        class Broken(Conn):
            async def send(self, data):
                raise OSError("gone")
        old = Conn("old")
        line = live_link.LiveLine(old)
        line.listen_too(Broken("new"))
        await line.send(AUDIO)
        return old, line
    old, line = asyncio.run(go())
    assert len(old.sent) == 1 and line.standby is None


def test_a_session_that_waited_while_the_talk_went_on_is_started_again_with_all_of_it(monkeypatch):
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_QUIET_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_HEAR_S", 0.05)

    async def go():
        old = Conn("old")
        first, second = (Conn(n, [{"type": "session.started"}]) for n in ("first", "second"))
        line, home, state = live_link.LiveLine(old), Home(first), quiet_state()
        conns = [first, second]

        async def take():
            return conns.pop(0), True
        home._take_live = take
        state["last_audio_time"] = time.monotonic() + 0.3      # she talks for a while
        home._start_fresh(line, state, [("unlock", "U")], ["fallback"])
        await asyncio.sleep(0.1)
        state["dialog"] += [("bot", "eins"), ("user", "zwei"), ("bot", "drei")]   # three more turns
        await asyncio.wait_for(state["fresh_task"], 3)
        await asyncio.sleep(0.01)
        return line, first, second, home
    line, first, second, home = asyncio.run(go())
    assert line.ws is second and first.closed and len(home.payloads) == 2
    assert len(home.payloads[0][2]) == 2 and len(home.payloads[1][2]) == 5       # the second one knows it all


def test_while_a_tool_is_at_work_nothing_is_exchanged_and_then_the_notes_go_out(monkeypatch):
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_WAIT_MAX_S", 0.2)
    monkeypatch.setattr(talk_notes, "FRESH_AFTER_TOOL_S", 0.2)

    async def go():
        old, new = Conn("old"), Conn("new", [{"type": "session.started"}])
        line, home, state = live_link.LiveLine(old), Home(new), quiet_state(tools_running=1)
        home._start_fresh(line, state, [("known", "K")], [("known", "K")])
        await asyncio.wait_for(state["fresh_task"], 3)
        return line, old, home
    line, old, home = asyncio.run(go())
    assert line.ws is old and home.sent_items == [[("known", "K")]] and not home.payloads


def test_a_session_that_does_not_start_leaves_the_talk_as_it_is_and_hands_over_notes(monkeypatch):
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.05)
    monkeypatch.setattr(talk_notes, "FRESH_START_TIMEOUT_S", 0.2)

    async def go(new):
        old = Conn("old")
        line, home, state = live_link.LiveLine(old), Home(new), quiet_state()
        home._start_fresh(line, state, [("known", "K")], [("known", "as notes")])
        await asyncio.wait_for(state["fresh_task"], 3)
        await asyncio.sleep(0.01)
        return line, old, home, new
    for new in (None, Conn("silent"), Conn("refuses", [{"type": "error", "error": {"message": "too long"}}])):
        line, old, home, conn = asyncio.run(go(new))
        assert line.ws is old and not old.closed and home.sent_items == [[("known", "as notes")]]
        assert conn is None or conn.closed


def test_the_setting_decides_and_the_code_word_replaces_the_note_for_a_known_metin():
    old = Conn("old")
    line = live_link.LiveLine(old)
    assert Home(frisch=1)._fresh_wanted(line, {}) and not Home(frisch=0)._fresh_wanted(line, {})
    assert not Home(frisch=1)._fresh_wanted(old, {})                       # a plain connection: no
    assert not Home(frisch=1)._fresh_wanted(line, {"closing": True})
    assert not Home(frisch=1)._fresh_wanted(line, {"start_refused": True})

    async def go():
        home, state = Home(None), quiet_state()
        home._start_fresh(line, state, [("mood", "M"), ("known", "K1"), ("diary", "open part")], [])
        home._start_fresh(line, state, [("unlock", "U"), ("known", "K2"), ("diary", "with private"),
                                        ("private", "P")], [], renew=("known", "diary"))
        await asyncio.wait_for(state["fresh_task"], 3)
        return state["start_items"], home.sent_items
    items, sent = asyncio.run(go())
    assert items == [("unlock", "U"), ("known", "K2"), ("diary", "with private"), ("private", "P")]
    assert len(sent) == 1        # only the newest request hands over its notes when it fails


def test_a_second_person_in_the_same_talk_is_added_not_put_in_place_of_the_first():
    async def go():
        line, home, state = live_link.LiveLine(Conn("old")), Home(None), quiet_state()
        home._start_fresh(line, state, [("known", "about the first"), ("diary", "her days with the first")], [])
        home._start_fresh(line, state, [("known", "about the second"), ("diary", "her days with the second")], [])
        await asyncio.wait_for(state["fresh_task"], 3)
        return state["start_items"]
    assert [t for k, t in asyncio.run(go()) if k == "known"] == ["about the first", "about the second"]
