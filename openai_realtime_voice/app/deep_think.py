"""
Deep thinking on demand.

GPT Live can only set the reasoning depth of its backend model for the whole session, not per
question. The session therefore runs with a low effort (fast answers), and for hard questions
the backend calls this tool, which asks the same model once with a high effort. Easy questions
never touch it, so they stay fast and cheap.
"""
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEEP_EFFORT = "high"
MAX_OUTPUT_TOKENS = 1500
TIMEOUT_S = 60.0

DEEP_TOOL = {
    "type": "function",
    "name": "tief_nachdenken",
    "description": (
        "Thinks a hard question through carefully and returns a considered answer. Use it only "
        "when the answer needs real reasoning: weighing options or comparing, advice on a "
        "decision, health, money or legal questions, explaining why or how something works, "
        "multi step calculations, planning, or when the user asks to think harder "
        "(denk genauer nach, daha dikkatli düşün). Do NOT use it for weather, time, switching "
        "devices, simple facts, small talk or anything a quick answer covers; when in doubt, "
        "answer quickly yourself. It takes a few seconds longer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "frage": {
                "type": "string",
                "description": "The complete question with all context needed, in the user's language.",
            },
        },
        "required": ["frage"],
        "additionalProperties": False,
    },
}

DEEP_BACKEND_HINT = (
    " MANDATORY: for hard questions (weighing or comparing options, advice on purchases or "
    "decisions, health, money, legal, why or how explanations, multi step calculations, "
    "planning, or when asked to think harder) you must ALWAYS call tief_nachdenken first, with "
    "the full question and every relevant fact from the conversation (for example what the "
    "household already owns), and answer only from its result, briefly and spoken. Never answer "
    "such a question from your own quick reasoning. For everything simple (weather, time, "
    "devices, facts, small talk) do not use it and answer right away."
)

DEEP_INSTRUCTIONS = (
    "Du beantwortest eine schwierige Frage für einen Sprachassistenten. Denke gründlich nach "
    "und antworte in der Sprache der Frage, klar und gesprochen formuliert, ohne Listen oder "
    "Markdown, in höchstens etwa sechs Sätzen. Nenne zuerst das Ergebnis, dann das Wichtigste "
    "zur Begründung. Sage ehrlich, wenn etwas unsicher ist."
)


def extract_text(data: dict) -> str:
    text = data.get("output_text") or ""
    if not text:
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
    return text.strip()


async def think(api_key: str, model: str, args: dict, url: str = RESPONSES_URL,
                transport: Optional[httpx.AsyncBaseTransport] = None) -> dict:
    """Ask the model once with a high reasoning effort. Returns {"antwort": ...} or {"error": ...}."""
    question = str(args.get("frage") or "").strip()
    if not question:
        return {"error": "Keine Frage übergeben."}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "instructions": DEEP_INSTRUCTIONS,
                "input": question,
                "reasoning": {"effort": DEEP_EFFORT},
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
        )
    if resp.status_code != 200:
        logger.warning("Deep think failed: HTTP %s %s", resp.status_code, resp.text[:300])
        return {"error": "Das gründliche Nachdenken hat gerade nicht geklappt."}
    text = extract_text(resp.json())
    if not text:
        return {"error": "Keine Antwort erhalten."}
    return {"antwort": text, "dauer_s": round(time.monotonic() - started, 1)}
