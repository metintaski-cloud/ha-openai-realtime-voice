"""One text answer for the background jobs (memory update, nightly cleanup, rudeness report).

Each OpenAI model is asked in turn (Responses API). The caller passes `check(text)`: an answer
it cannot use counts as no answer, so the next model is asked.
"""

import logging
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)


def output_text(data: dict) -> str:
    """The text of a Responses API answer."""
    text = data.get("output_text") or ""
    if not text:
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
    return text


async def ask(prompt: str, api_key: str, models: list, url: str, label: str,
              check: Callable[[str], bool] = bool, timeout: float = 90.0,
              extra: Optional[dict] = None) -> Optional[str]:
    """The first usable answer of the models, or None. `extra`: more fields for the request
    (a reasoning effort, an output limit)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in [m for m in models if m]:
            try:
                resp = await client.post(
                    url, headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"},
                    json={"model": model, "input": prompt, **(extra or {})})
            except Exception as e:
                logger.warning("%s request failed (%s): %s", label, model, e)
                continue
            if resp.status_code != 200:
                logger.warning("%s with model %s failed: HTTP %s %s", label, model,
                               resp.status_code, resp.text[:300])
                continue
            text = output_text(resp.json())
            if check(text):
                return text
            logger.warning("%s: answer of %s not usable: %r", label, model, text[:300])
    return None
