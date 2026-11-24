"""Backend functions (tools) of the bridge: which tool runs how, and the generic runner.

Mixed into LiveVoiceBridge; needs self.admin_key, self.monthly_budget, self.code_phrase, self.todo_sync and the
tool objects (self.lights, self.fan, self.vacuum, self.purifier, self.tv, self.technik, self.cleaner,
self.messages) from it. To add a tool see "Adding a tool" in AGENTS.md."""
import asyncio
import json
import logging

from app import agenda, befehle, cleanup, diary, heart, mood, reminders, costs, fan, inbox, lights, mail, messages, purifier, technik, vacuum

logger = logging.getLogger(__name__)


class ToolLinkMixin:
    @staticmethod
    def _tool_args(raw_args) -> dict:
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except json.JSONDecodeError:
            return {}
        return args if isinstance(args, dict) else {}

    def _only_metin(self, state: dict) -> bool:
        """True when the bridge itself heard the code phrase in this session."""
        return bool(self.code_phrase and state.get("unlocked"))

    def _build_tools(self) -> dict:
        """Backend function name -> how to run it, all served by the generic _run_tool.
        run(args) is awaited with a timeout, gate(args, state) may return an error result
        instead (only Metin), after(args, result) runs on success, log(args, result) is what
        goes to the log, phase is sent to the client first."""
        def metin_error(what):
            return {"error": f"Nicht erlaubt: {what} nur Metin, und nur nachdem er das "
                             "Codewort gesagt hat."}

        def technik_gate(args, state):
            if args.get("action") in ("zeit_aendern", "licht_aendern", "lampen_aendern",
                                      "ventilator_aendern", "nacht_aendern") \
                    and not self._only_metin(state):
                return metin_error("Zeiten, Lampen und Ventilator in Automationen ändert")

        def cleanup_gate(args, state):
            if not self._only_metin(state):
                return metin_error("Das Gedächtnis räumt")

        def mail_gate(args, state):
            if not self._only_metin(state):
                return metin_error("E-Mails schreibt")

        def inbox_gate(args, state):
            if not self._only_metin(state):
                return metin_error("Mails liest")

        def agenda_gate(args, state):
            if not self._only_metin(state):
                return metin_error("Termine verwaltet")

        def command_gate(args, state):  # code word, or Metin known by his words
            if not (self._only_metin(state) or state.get("metin_known")):
                return {"error": "Nicht erlaubt: Feste Befehle legt nur Metin fest. Frag, wer "
                                 "spricht; ist es Metin, soll er es selbst sagen."}

        async def command_set(args):
            return self.commands.define(args)

        def mood_gate(args, state):  # code word, or Metin known by his words
            if not (self._only_metin(state) or state.get("metin_known")):
                return metin_error("Laune")

        def remember_gate(args, state):  # who said it: the bridge knows, not the model
            names = sorted(state.get("identified") or [])
            metin = next((n for n in names if n.split()[0] == "Metin"), "")
            if not metin and (self._only_metin(state) or state.get("metin_known")):
                metin = "Metin"
            args["_wer"] = metin or (names[0] if len(names) == 1 else "")
            args["_privat_ok"] = self._only_metin(state)  # private only after the code word

        async def remember_run(args):
            ok = self.diary.remember(args.get("text"), args.get("_wer", ""),
                                     bool(args.get("privat")) and args.get("_privat_ok"),
                                     ask_at=diary.event_time(args.get("datum"), args.get("uhrzeit")))
            return {"ok": ok}

        async def recall_run(args):  # same speaker logic as merken (remember_gate)
            note = await self.recall.ask(args.get("suche", ""), args.get("_wer", ""),
                                         bool(args.get("_privat_ok")))
            return {"erinnerung": note.strip()}

        def mood_after(args, result):
            if self.lamp.mood_pct is not None:  # only in a voice talk after the code word
                self.lamp.set_mood_pct(self.mood.lamp_pct())

        def cleanup_after(args, result):
            if args.get("action") == "streichen" and self.todo_sync:
                self.todo_sync.kick()

        return {
            costs.COSTS_TOOL["name"]: {
                "label": "Costs", "phase": "thinking", "timeout": 15.0,
                "run": lambda a: costs.cost_report(self.admin_key, self.monthly_budget),
                "error": "Could not read OpenAI costs right now.",
                "log": lambda a, r: "done"},
            lights.LIGHTS_TOOL["name"]: {
                "label": "Lights", "timeout": 25.0, "run": self.lights.run,
                "error": "Die Lampen konnten gerade nicht gesteuert werden."},
            befehle.RUN_TOOL["name"]: {
                "label": "Fixed command", "timeout": 30.0, "run": self.commands.run,
                "error": "Der feste Befehl konnte gerade nicht ausgeführt werden.",
                "log": lambda a, r: f"{a.get('name')} -> " + (
                    "ok" if r.get("ok") else str(r.get("probleme") or r.get("error", ""))[:80])},
            befehle.SET_TOOL["name"]: {
                "label": "Fixed command set", "timeout": 5.0, "run": command_set,
                "gate": command_gate, "error": "Der feste Befehl konnte gerade nicht geändert werden.",
                "log": lambda a, r: f"{a.get('name')} -> " + str(
                    r.get("gilt_jetzt") or r.get("geloescht") or r.get("error", ""))[:80]},
            fan.FAN_TOOL["name"]: {
                "label": "Fan", "timeout": 15.0, "run": self.fan.run,
                "error": "Der Ventilator konnte gerade nicht gesteuert werden."},
            vacuum.VACUUM_TOOL["name"]: {
                "label": "Vacuum", "timeout": 20.0, "run": self.vacuum.run,
                "error": "Der Saugroboter konnte gerade nicht gesteuert werden."},
            purifier.PURIFIER_TOOL["name"]: {
                "label": "Purifier", "timeout": 15.0, "run": self.purifier.run,
                "error": "Der Luftreiniger konnte gerade nicht gesteuert werden."},
            "fernseher_steuern": {
                "label": "TV", "timeout": 20.0, "run": self.tv.run,
                "error": "Der Fernseher konnte gerade nicht gesteuert werden."},
            technik.TECHNIK_TOOL["name"]: {
                "label": "Technik", "timeout": 15.0, "run": self.technik.run,
                "gate": technik_gate,
                "error": "Die Technik konnte gerade nicht geprüft werden.",
                "log": lambda a, r: f"{a} -> {r.get('treffer')} hits"},
            cleanup.CLEANUP_TOOL["name"]: {
                "label": "Cleanup", "timeout": 60.0, "run": self.cleaner.run,
                "gate": cleanup_gate, "after": cleanup_after,
                "error": "Das Aufräumen hat gerade nicht geklappt.",
                "log": lambda a, r: f"{a.get('action')} -> " + str(
                    {k: v for k, v in r.items() if k != "vorschlaege"})},
            mail.EMAIL_TOOL["name"]: {
                "label": "Mail draft", "timeout": 10.0, "run": self.mailer.run,
                "gate": mail_gate, "error": "Der Entwurf konnte gerade nicht angelegt werden.",
                "log": lambda a, r: "ok" if r.get("ok") else str(r.get("error", ""))[:60]},
            inbox.INBOX_TOOL["name"]: {
                "label": "Mail inbox", "timeout": 30.0, "run": self.inbox.run,
                "gate": inbox_gate, "error": "Der Posteingang ist gerade nicht erreichbar.",
                "log": lambda a, r: f"{a.get('aktion')} -> " + (
                    str(r.get("anzahl", "ok")) if r.get("ok") else str(r.get("error", ""))[:60])},
            agenda.AGENDA_TOOL["name"]: {
                "label": "Calendar", "timeout": 30.0, "run": self.agenda.run,
                "gate": agenda_gate, "error": "Der Kalender ist gerade nicht erreichbar.",
                "log": lambda a, r: f"{a.get('aktion')} -> " + (
                    str(r.get("anzahl", "ok")) if r.get("ok") else str(r.get("error", ""))[:60])},
            reminders.OK_TOOL["name"]: {
                "label": "Reminder", "timeout": 15.0, "run": self.reminders.run_ok,
                "error": "Das ging gerade nicht.",
                "log": lambda a, r: str(r.get("anzahl", r.get("error", "")))[:40]},
            heart.MOOD_TOOL["name"]: {
                "label": "Mood", "timeout": 5.0, "run": self.mood.run, "gate": mood_gate,
                "after": mood_after, "error": "Das ging gerade nicht.",
                "log": lambda a, r: f"{a.get('aktion')} -> " + str(r.get("stimmung", r.get("error", "")))[:40]},
            diary.MERKEN_TOOL["name"]: {
                "label": "Remember", "timeout": 5.0, "run": remember_run, "gate": remember_gate,
                "error": "Das konnte ich mir gerade nicht merken.",
                "log": lambda a, r: ("ok " if r.get("ok") else "no ") + (a.get("_wer") or "unknown")},
            diary.ERINNERN_TOOL["name"]: {
                "label": "Recall", "timeout": 8.0, "run": recall_run, "gate": remember_gate,
                "error": "Daran komme ich gerade nicht heran.",
                "log": lambda a, r: a.get("_wer") or "unknown"},
            messages.TO_METIN_TOOL["name"]: {
                "label": "Message", "timeout": 20.0, "run": self.messages.to_metin,
                "error": "Die Nachricht konnte gerade nicht gesendet werden.",
                "log": lambda a, r: "done"},
        }

    async def _run_tool(self, spec: dict, live_ws, call_id: str, raw_args, state: dict) -> None:
        """Run one backend function without blocking the audio loop and return its result."""
        args = self._tool_args(raw_args)
        state["tools_running"] = state.get("tools_running", 0) + 1  # no session change meanwhile
        try:
            blocked = spec["gate"](args, state) if spec.get("gate") else None
            if blocked is not None:
                result = blocked
            else:
                result = await asyncio.wait_for(spec["run"](args), timeout=spec["timeout"])
                if spec.get("after"):
                    spec["after"](args, result)
        except Exception as e:
            logger.warning("%s failed: %s", spec["label"], e)
            result = {"error": spec["error"]}
        log = spec.get("log")
        logger.info("%s %s", spec["label"], log(args, result) if log else f"{args} -> {result}")
        try:
            await self._send_function_output(live_ws, call_id, result)
        except Exception as e:
            logger.warning("Could not return %s result: %s", spec["label"], e)
        finally:
            state["tools_running"] = max(0, state.get("tools_running", 1) - 1)

    async def _send_function_output(self, live_ws, call_id: str, output: dict) -> None:
        """Return a function result to the backend and let it continue."""
        await live_ws.send(
            json.dumps({
                "type": "response.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output),
                },
            })
        )
        await live_ws.send(json.dumps({"type": "response.create"}))
