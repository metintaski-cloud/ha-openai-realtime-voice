"""Backend functions (tools) of the bridge: which tool runs how, and the generic runner.

Mixed into LiveVoiceBridge; needs self.admin_key, self.monthly_budget, self.code_phrase, self.todo_sync and the
tool objects (self.lights, self.fan, self.vacuum, self.purifier, self.tv, self.technik, self.cleaner,
self.messages) from it. To add a tool see "Adding a tool" in AGENTS.md."""
import asyncio
import json
import logging

from app import cleanup, costs, fan, lights, messages, purifier, technik, vacuum

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
            messages.TO_METIN_TOOL["name"]: {
                "label": "Message", "timeout": 20.0, "run": self.messages.to_metin,
                "error": "Die Nachricht konnte gerade nicht gesendet werden.",
                "log": lambda a, r: "done"},
        }

    async def _run_tool(self, spec: dict, live_ws, call_id: str, raw_args, state: dict) -> None:
        """Run one backend function without blocking the audio loop and return its result."""
        args = self._tool_args(raw_args)
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
