"""HTTPS copy of the app (2.145.0): Chrome only starts the installed app in full screen from a
real secure address, so the page is also served over HTTPS once a certificate is there."""
import asyncio
import os
import ssl
import subprocess

import pytest

from app import memory_web, tls


def _cert(folder, name="a"):
    cert, key = str(folder / f"{name}.pem"), str(folder / f"{name}.key")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", "/CN=leyla.test", "-keyout", key, "-out", cert],
                   check=True, capture_output=True)
    return cert, key


def test_without_a_certificate_nothing_changes(tmp_path):
    assert tls.context(str(tmp_path / "no.pem"), str(tmp_path / "no.key")) is None
    (tmp_path / "bad.pem").write_text("not a certificate")
    (tmp_path / "bad.key").write_text("not a key")
    assert tls.context(str(tmp_path / "bad.pem"), str(tmp_path / "bad.key")) is None


def test_the_page_answers_over_https(tmp_path):
    cert, key = _cert(tmp_path)
    ctx = tls.context(cert, key)
    assert ctx is not None

    async def go():
        server = await memory_web.start_http(memory_web.memory.MemoryStore(str(tmp_path / "m.json")),
                                             None, host="127.0.0.1", port=0, tls=ctx)
        port = server.sockets[0].getsockname()[1]
        client = ssl.create_default_context()
        client.check_hostname = False
        client.verify_mode = ssl.CERT_NONE
        r, w = await asyncio.open_connection("127.0.0.1", port, ssl=client)
        w.write(b"GET /manifest.json HTTP/1.1\r\n\r\n")
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return data

    data = asyncio.run(go())
    assert b"200 OK" in data.split(b"\r\n")[0] and b'"fullscreen"' in data


def test_watch_starts_once_when_the_certificate_appears_and_loads_a_renewed_one(tmp_path, monkeypatch):
    cert, key = str(tmp_path / "fullchain.pem"), str(tmp_path / "privkey.pem")
    monkeypatch.setattr(tls, "CERT", cert)
    monkeypatch.setattr(tls, "KEY", key)
    started = []

    async def start(ctx):
        started.append(ctx)

    async def go():
        task = asyncio.create_task(tls.watch(start, check_s=0.05))
        await asyncio.sleep(0.15)
        assert started == [], "no certificate yet"
        c, k = _cert(tmp_path, "one")
        os.replace(k, key)
        os.replace(c, cert)
        await asyncio.sleep(0.3)
        assert len(started) == 1
        c, k = _cert(tmp_path, "two")
        later = os.path.getmtime(cert) + 5
        os.replace(k, key)
        os.replace(c, cert)
        os.utime(cert, (later, later))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert len(started) == 1, "a renewed certificate goes into the same context, no second start"


def test_live_talk_uses_wss_on_the_secure_page():
    assert "'wss://'+location.hostname+':8443'" in memory_web.PAGE
