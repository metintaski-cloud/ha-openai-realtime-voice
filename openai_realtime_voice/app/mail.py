"""E-mails from Leyla, only after Metin's tap on "Senden" in the app chat.

Leyla (by voice through the tool `email_entwurf`, or in the app chat) only writes a draft for a
name from the fixed contact list (option `email_contacts`, "Name: adresse; Name: adresse"); a
dictated address is never used, because one misheard letter sends the mail to a stranger. The
draft waits in /data/mail_drafts.json and shows as a card in the app chat; only the "Senden"
button there sends it through Metin's Gmail (option `email_address`, `email_app_password`, an app
password from his Google account). Texts and addresses are never logged.
"""

import asyncio
import json
import logging
import os
import re
import smtplib
import ssl
import time
import unicodedata
import uuid
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587
DRAFTS_PATH = "/data/mail_drafts.json"
MAX_DRAFTS = 20
DRAFT_TTL_S = 24 * 3600
MAX_TEXT = 5000

EMAIL_TOOL = {
    "type": "function",
    "name": "email_entwurf",
    "description": (
        "Writes an e-mail draft from Metin's Gmail to one person of his contact list. Nothing is "
        "sent: the draft appears in the chat of Metin's Leyla app and only his tap on 'Senden' "
        "there sends it. Use it when Metin asks to send or write an e-mail (Mail, E-Mail, "
        "e-posta) to someone."),
    "parameters": {
        "type": "object",
        "properties": {
            "an": {"type": "string", "description": "Name of the person as Metin said it."},
            "adresse": {"type": "string", "description": "Only for an address you found with "
                        "the web search (a company, office, shop); never one Metin dictated. "
                        "Leave out for people of his contacts."},
            "betreff": {"type": "string", "description": "Short subject line."},
            "text": {"type": "string", "description": "The whole mail text, ready to send, "
                     "in the language Metin wants, signed with Metin."},
        },
        "required": ["an", "betreff", "text"],
        "additionalProperties": False,
    },
}

EMAIL_BACKEND_HINT = (
    " E-mail (email_entwurf): only for Metin after the code word. Write subject and text from "
    "what he says, then tell him in one sentence that the draft is in the chat of his app and "
    "goes out only when he taps Senden there. Never say it was sent. If the name is not in the "
    "contact list, say so and name the people you can write to. For a company or office you may "
    "look up its address with the web search and pass it as adresse; the card then asks Metin "
    "to check it.")

MAIL_NOTE = """

E-MAIL
• Bittet Metin dich, eine E-Mail zu schreiben oder zu schicken, trägst du sie unter "email" ein: {{"to": Name aus der Liste, "subject": kurzer Betreff, "body": fertiger Text, mit Metin unterschrieben}}. Verschickt wird nichts von dir: In der App erscheint eine Karte, und erst Metins Tipp auf "Senden" schickt sie ab. Sag also nie, sie sei verschickt, sondern dass sie unten zum Senden bereitliegt.
• Nur an diese Kontakte: {names}. Steht der Name nicht dabei, sag es ihm und schreib keine Mail; Adressen, die er diktiert, nimmst du nicht."""


ADDR_RE = re.compile(r"[^@\s<>,;]+@[^@\s<>,;]+\.[a-z]{2,}", re.I)


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower().replace("ı", "i"))
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def parse_contacts(raw: str) -> dict:
    """{"Ayşe": "a@b.de", ...} from "Ayşe: a@b.de; Umut: c@d.de" (also new lines)."""
    out = {}
    for part in (raw or "").replace("\n", ";").split(";"):
        name, sep, addr = part.partition(":")
        name, addr = name.strip(), addr.strip()
        if sep and name and "@" in addr and " " not in addr:
            out[name] = addr
    return out


class Mailer:
    def __init__(self, address: str = "", password: str = "", contacts: str = "",
                 path: Optional[str] = None, google=None) -> None:
        def opt(v):
            v = (v or "").strip()
            return "" if v.lower() == "null" else v
        self.address = opt(address or os.environ.get("EMAIL_ADDRESS"))
        self.password = opt(password or os.environ.get("EMAIL_APP_PASSWORD")).replace(" ", "")
        self.fixed = parse_contacts(opt(contacts or os.environ.get("EMAIL_CONTACTS")))
        self.google = google  # gcontacts.GoogleContacts: the Google contacts Metin ticked
        self.path = path or os.environ.get("MAIL_DRAFTS_PATH", DRAFTS_PATH)

    @property
    def contacts(self) -> dict:
        """Everyone Leyla may write to: the option list plus the ticked Google contacts."""
        out = dict(self.google.allowed_contacts()) if self.google else {}
        out.update(self.fixed)
        return out

    @property
    def via_google(self) -> bool:
        return bool(self.google and self.google.connected)

    @property
    def available(self) -> bool:
        """Sending works through the Google sign in (2.82.1) or an app password (2.81.0)."""
        return self.via_google or bool(self.address and self.password)

    def names(self) -> str:
        return ", ".join(self.contacts) or "(keine)"

    def resolve(self, name: str) -> Optional[str]:
        """The contact name meant by what was said, or None."""
        said = _norm(name)
        if not said:
            return None
        contacts = self.contacts
        for n in contacts:
            if _norm(n) == said:
                return n
        hits = [n for n in contacts
                if _norm(n).split()[0] in said.split() or said.split()[0] == _norm(n).split()[0]]
        return hits[0] if len(hits) == 1 else None

    # ---- drafts ----
    def _load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                drafts = json.load(f)
        except Exception:
            return []
        now = time.time()
        return [d for d in drafts if isinstance(d, dict) and now - d.get("at", 0) < DRAFT_TTL_S]

    def _save(self, drafts: list) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(drafts[-MAX_DRAFTS:], f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def draft(self, to: str, subject: str, body: str, web_addr: str = "") -> dict:
        """A new draft for a contact (or an address found on the web), or an error naming the
        possible people."""
        if not self.available:
            return {"error": "E-Mail ist nicht eingerichtet."}
        contacts = self.contacts
        name = self.resolve(to)
        web_addr = (web_addr or "").strip()
        if name:
            addr, web = contacts[name], False
        elif ADDR_RE.fullmatch(web_addr):
            name, addr, web = (to or "").strip() or web_addr, web_addr, True
        else:
            return {"error": f"'{to}' steht nicht in Metins E-Mail Kontakten.",
                    "kontakte": list(contacts)}
        body = (body or "").strip()[:MAX_TEXT]
        if not body:
            return {"error": "Der Text fehlt."}
        d = {"id": uuid.uuid4().hex[:12], "to": name, "addr": addr, "web": web,
             "subject": (subject or "").strip()[:200] or "(ohne Betreff)", "body": body,
             "at": time.time()}
        drafts = self._load() + [d]
        self._save(drafts)
        logger.info("Mail draft for a contact created (%d waiting)", len(drafts))
        return {"ok": True, "id": d["id"], "an": name,
                "hinweis": "Entwurf liegt im Chat der App, erst Metins Tipp auf Senden schickt ihn."}

    def pending(self) -> list:
        return [{**{k: d[k] for k in ("id", "to", "addr", "subject", "body")},
                 "web": bool(d.get("web"))} for d in self._load()]

    def discard(self, draft_id: str) -> bool:
        drafts = self._load()
        rest = [d for d in drafts if d["id"] != draft_id]
        self._save(rest)
        return len(rest) < len(drafts)

    def _message(self, d: dict) -> EmailMessage:
        msg = EmailMessage()
        if self.address:
            msg["From"] = self.address
        msg["To"], msg["Subject"] = d["addr"], d["subject"]
        msg.set_content(d["body"])
        return msg

    def _smtp_send(self, d: dict) -> None:
        msg = self._message(d)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(self.address, self.password)
            s.send_message(msg)

    async def send(self, draft_id: str) -> dict:
        """Send one waiting draft (Metin tapped Senden)."""
        drafts = self._load()
        d = next((x for x in drafts if x["id"] == draft_id), None)
        if not d:
            return {"ok": False, "error": "Entwurf nicht mehr da (älter als 24 Stunden?)."}
        try:
            if self.via_google:
                if not await self.google.send(self._message(d)):
                    return {"ok": False, "error": "Senden ging nicht. In der App unter Google "
                                                  "Kontakte neu verbinden?"}
            else:
                await asyncio.to_thread(self._smtp_send, d)
        except Exception as e:
            logger.warning("Mail could not be sent: %s", type(e).__name__)
            return {"ok": False, "error": "Senden ging nicht. Stimmt das App Passwort?"}
        self._save([x for x in drafts if x["id"] != draft_id])
        logger.info("Mail sent after Metin's tap")
        return {"ok": True}

    async def run(self, args: dict) -> dict:
        """The voice tool email_entwurf."""
        return self.draft(args.get("an", ""), args.get("betreff", ""), args.get("text", ""),
                          args.get("adresse", ""))
