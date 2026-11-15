"""Metin's Google account for Leyla's e-mails: contacts (read only) and sending, add on 2.82.0.

Google allows contacts only through OAuth since March 2025, so Metin creates a small OAuth client
of the type "Desktop app" in his Google Cloud project (options `google_client_id`,
`google_client_secret`). In the memory app he taps "Google Kontakte verbinden", signs in, and
pastes the address of the page Google sends him to (http://127.0.0.1/?code=..., which does not
load on the phone; only its code counts). The refresh token is kept in /data/google_token.json.

Leyla may write only to contacts Metin ticked in the app (/data/mail_allowed.json, by address).
Since 2.82.1 mails go out through the Gmail API with the same sign in (scope gmail.send), because
app passwords need two step verification, which Metin's account does not use. Names and addresses
are never logged.
"""

import base64
import json
import logging
import os
import time
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SCOPE = ("https://www.googleapis.com/auth/contacts.readonly "
         "https://www.googleapis.com/auth/gmail.send")
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
REDIRECT = "http://127.0.0.1"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections"
REFRESH_S = 6 * 3600  # the contact list is read again at most every 6 hours


def _opt(v: Optional[str]) -> str:
    v = (v or "").strip()
    return "" if v.lower() == "null" else v


def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def code_from(pasted: str) -> str:
    """The authorization code from the pasted address (or the bare code)."""
    pasted = (pasted or "").strip()
    if "code=" in pasted:
        query = urllib.parse.urlparse(pasted).query or pasted.split("?", 1)[-1]
        return (urllib.parse.parse_qs(query).get("code") or [""])[0]
    return pasted if pasted and " " not in pasted else ""


class GoogleContacts:
    def __init__(self, client_id: str = "", client_secret: str = "", data_dir: str = "") -> None:
        self.client_id = _opt(client_id or os.environ.get("GOOGLE_CLIENT_ID"))
        self.client_secret = _opt(client_secret or os.environ.get("GOOGLE_CLIENT_SECRET"))
        base = data_dir or os.environ.get("GOOGLE_DATA_DIR", "/data")
        self.token_path = os.path.join(base, "google_token.json")
        self.cache_path = os.path.join(base, "google_contacts.json")
        self.allowed_path = os.path.join(base, "mail_allowed.json")
        self._access, self._access_until = "", 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def connected(self) -> bool:
        return self.configured and bool(_read(self.token_path, {}).get("refresh_token"))

    def auth_url(self) -> str:
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id, "redirect_uri": REDIRECT, "response_type": "code",
            "scope": SCOPE, "access_type": "offline", "prompt": "consent"})

    async def connect(self, pasted: str) -> dict:
        """Exchange the pasted code for a refresh token."""
        code = code_from(pasted)
        if not self.configured or not code:
            return {"ok": False, "error": "Kein Code gefunden. Füge die ganze Adresse ein."}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(TOKEN_URL, data={
                "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
        data = resp.json() if resp.status_code == 200 else {}
        if not data.get("refresh_token"):
            logger.warning("Google contacts: sign in failed (HTTP %s)", resp.status_code)
            return {"ok": False, "error": "Google hat den Code nicht angenommen. Bitte nochmal "
                                          "verbinden, der Code gilt nur kurz."}
        _write(self.token_path, {"refresh_token": data["refresh_token"]})
        self._access, self._access_until = data.get("access_token", ""), \
            time.time() + float(data.get("expires_in", 0)) - 60
        logger.info("Google contacts connected")
        await self.contacts(force=True)
        return {"ok": True}

    async def _token(self, client) -> str:
        if self._access and time.time() < self._access_until:
            return self._access
        refresh = _read(self.token_path, {}).get("refresh_token")
        if not refresh:
            return ""
        resp = await client.post(TOKEN_URL, data={
            "refresh_token": refresh, "client_id": self.client_id,
            "client_secret": self.client_secret, "grant_type": "refresh_token"})
        if resp.status_code != 200:
            logger.warning("Google contacts: token refresh failed (HTTP %s)", resp.status_code)
            return ""
        data = resp.json()
        self._access = data.get("access_token", "")
        self._access_until = time.time() + float(data.get("expires_in", 0)) - 60
        return self._access

    async def contacts(self, force: bool = False) -> list:
        """[{"name", "addr"}] of all contacts with an e-mail address (cached for 6 hours)."""
        cache = _read(self.cache_path, {})
        if not force and cache.get("list") is not None and \
                time.time() - cache.get("at", 0) < REFRESH_S:
            return cache["list"]
        if not self.connected:
            return cache.get("list") or []
        found, page = [], ""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                token = await self._token(client)
                if not token:
                    return cache.get("list") or []
                for _ in range(20):
                    params = {"personFields": "names,emailAddresses", "pageSize": 1000}
                    if page:
                        params["pageToken"] = page
                    resp = await client.get(PEOPLE_URL, params=params,
                                            headers={"Authorization": f"Bearer {token}"})
                    if resp.status_code != 200:
                        logger.warning("Google contacts: list failed (HTTP %s)", resp.status_code)
                        return cache.get("list") or []
                    data = resp.json()
                    for p in data.get("connections", []):
                        name = ((p.get("names") or [{}])[0].get("displayName") or "").strip()
                        for e in p.get("emailAddresses") or []:
                            addr = (e.get("value") or "").strip()
                            if "@" in addr:
                                found.append({"name": name or addr, "addr": addr})
                    page = data.get("nextPageToken", "")
                    if not page:
                        break
        except Exception as e:
            logger.warning("Google contacts could not be read: %s", type(e).__name__)
            return cache.get("list") or []
        found.sort(key=lambda c: c["name"].lower())
        _write(self.cache_path, {"at": time.time(), "list": found})
        logger.info("Google contacts read: %d addresses", len(found))
        return found

    async def send(self, message) -> bool:
        """Send an email.message.EmailMessage from Metin's Gmail (Metin tapped Senden)."""
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._token(client)
            if not token:
                return False
            resp = await client.post(SEND_URL, json={"raw": raw},
                                     headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            logger.warning("Gmail send failed (HTTP %s)", resp.status_code)
        return resp.status_code == 200

    # ---- which contacts Leyla may write to ----
    def allowed(self) -> set:
        return {a.lower() for a in _read(self.allowed_path, [])}

    def set_allowed(self, addr: str, on: bool) -> None:
        addrs = self.allowed()
        (addrs.add if on else addrs.discard)((addr or "").strip().lower())
        _write(self.allowed_path, sorted(a for a in addrs if "@" in a))

    def allowed_contacts(self) -> dict:
        """{"Name": "addr"} of the ticked Google contacts, from the cache (no network)."""
        ok = self.allowed()
        out = {}
        for c in _read(self.cache_path, {}).get("list") or []:
            if c["addr"].lower() in ok and c["name"] not in out:
                out[c["name"]] = c["addr"]
        return out
