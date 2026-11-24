"""HTTPS for the app (2.145.0, Metin wants the app to open in full screen at once).

Chrome starts an installed app without its bars only from a real secure address. With the
plain home address (http://192.168.2.240:8082) the installed app opened as a tab with the
address bar, however it was installed (tested with Metin on 24 Nov 2026). So the page is
also served over HTTPS on the default port 443, and live talk over wss on 8443, as soon as
a certificate lies in Home Assistant's /ssl folder (the Duck DNS add on puts a Let's
Encrypt certificate there and renews it). Without a certificate nothing changes.
"""
import asyncio
import logging
import os
import ssl
from typing import Optional

logger = logging.getLogger(__name__)

CERT = os.environ.get("LEYLA_TLS_CERT", "/ssl/fullchain.pem")
KEY = os.environ.get("LEYLA_TLS_KEY", "/ssl/privkey.pem")
HTTPS_PORT = int(os.environ.get("LEYLA_TLS_PORT", "443"))
WSS_PORT = int(os.environ.get("LEYLA_WSS_PORT", "8443"))
CHECK_S = 60


def stamp(cert: str = "", key: str = "") -> float:
    """Newest change of the two files, 0 when one is missing."""
    try:
        return max(os.path.getmtime(cert or CERT), os.path.getmtime(key or KEY))
    except OSError:
        return 0.0


def context(cert: str = "", key: str = "") -> Optional[ssl.SSLContext]:
    """A server context with the certificate, or None when there is none or it does not load."""
    if not stamp(cert, key):
        return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert or CERT, key or KEY)
        return ctx
    except (ssl.SSLError, OSError) as e:
        logger.warning("TLS: certificate could not be loaded (%s)", e)
        return None


async def watch(start, check_s: float = CHECK_S) -> None:
    """Wait for a certificate, then call `await start(ctx)` once; afterwards load a renewed
    certificate into the same context, so new connections get it without a restart."""
    ctx, seen = None, 0.0
    while True:
        now = stamp()
        if ctx is None and now:
            ctx = context()
            if ctx is not None:
                seen = now
                try:
                    await start(ctx)
                    logger.info("TLS: serving with the certificate from %s", CERT)
                except Exception as e:
                    logger.warning("TLS: could not start (%s)", e)
        elif ctx is not None and now and now != seen:
            try:
                ctx.load_cert_chain(CERT, KEY)
                seen = now
                logger.info("TLS: renewed certificate loaded")
            except (ssl.SSLError, OSError) as e:
                logger.warning("TLS: renewed certificate could not be loaded (%s)", e)
        await asyncio.sleep(check_s)
