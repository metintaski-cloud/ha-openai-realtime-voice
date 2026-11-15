import pytest

from app import cleanup, memory, report, textmodel


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, ""

    def json(self):
        return self._b


def fake_client(calls, local_text=None, local_code=200, openai_text="OPENAI"):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append(url)
            if url.endswith("/chat/completions"):
                if local_text is None:
                    raise OSError("unreachable")
                return Resp(local_code, {"choices": [{"message": {"content": local_text}}]})
            return Resp(200, {"output_text": openai_text})
    return Client


LOCAL = {"url": "http://pc:11434/v1/", "key": "", "model": "gemma"}


@pytest.mark.asyncio
async def test_homeai_first_then_openai(monkeypatch):
    calls = []
    monkeypatch.setattr(textmodel.httpx, "AsyncClient", fake_client(calls, local_text="LOCAL"))
    assert await textmodel.ask("p", "k", ["m"], "https://o/v1/responses", "T", local=LOCAL) == "LOCAL"
    assert calls == ["http://pc:11434/v1/chat/completions"]
    calls.clear()
    monkeypatch.setattr(textmodel.httpx, "AsyncClient", fake_client(calls))  # PC off
    assert await textmodel.ask("p", "k", ["m"], "https://o/v1/responses", "T", local=LOCAL) == "OPENAI"
    assert calls == ["http://pc:11434/v1/chat/completions", "https://o/v1/responses"]
    calls.clear()
    monkeypatch.setattr(textmodel.httpx, "AsyncClient", fake_client(calls, local_text="kaputt"))
    out = await textmodel.ask("p", "k", ["m"], "https://o/v1/responses", "T",
                              check=lambda t: t != "kaputt", local=LOCAL)
    assert out == "OPENAI" and len(calls) == 2


def test_local_provider_from_options(monkeypatch):
    monkeypatch.delenv("CHAT_API_URL", raising=False)
    assert textmodel.local_provider() is None
    monkeypatch.setenv("CHAT_API_URL", "http://pc:11434/v1")
    monkeypatch.setenv("CHAT_MODEL", "gemma")
    monkeypatch.setenv("CHAT_API_KEY", "null")
    assert textmodel.local_provider() == {"url": "http://pc:11434/v1", "key": "", "model": "gemma"}


@pytest.mark.asyncio
async def test_background_jobs_use_homeai(monkeypatch, tmp_path):
    calls = []
    lists = '{"family": ["Person: Metin"], "friends": [], "private": [], "leyla": [], "confidential": []}'
    monkeypatch.setattr(textmodel.httpx, "AsyncClient", fake_client(calls, local_text=lists))
    out = await memory.summarize("k", ["m"], {"family": ["Person: Metin"]},
                                 [["user", "Hallo"], ["bot", "Hi"]], local=LOCAL)
    assert out["family"] == ["Person: Metin"] and calls[-1].endswith("/chat/completions")
    monkeypatch.setattr(textmodel.httpx, "AsyncClient", fake_client(calls, local_text="Umut war frech."))
    assert await report.write_report("k", ["m"], [["bot", "x"]], local=LOCAL) == "Umut war frech."
    monkeypatch.setenv("CHAT_API_URL", "http://pc:11434/v1")
    monkeypatch.setenv("CHAT_MODEL", "gemma")
    monkeypatch.setattr(textmodel.httpx, "AsyncClient",
                        fake_client(calls, local_text='{"streichen": [2]}'))
    c = cleanup.Cleaner(memory.MemoryStore(str(tmp_path / "m.json")), "k", ["m"])
    assert await c._ask([("family", "a"), ("family", "b")]) == [2]
