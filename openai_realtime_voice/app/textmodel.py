"""One text answer for the background jobs (memory update, nightly cleanup, rudeness report).

HomeAI first (`chat_api_url`, `chat_api_key`, `chat_model`: an OpenAI compatible chat
completions endpoint, for example Ollama on Metin's PC), so the family's data stays in the
house; OpenAI (Responses API) only when HomeAI is not set, off or gives no usable answer.
The caller passes `check(text)`: an answer it cannot use counts as no answer, so the next
model is asked.
"""

import logging
import os
import time
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

LOCAL_TIMEOUT_S = 300.0  # a long memory update on a 12 GB card takes a few minutes


def local_provider() -> Optional[dict]:
    """{"url", "key", "model"} of HomeAI from the add on options, or None."""
    def opt(name: str) -> str:
        v = (os.environ.get(name) or "").strip()
        return "" if v.lower() == "null" else v
    url, model = opt("CHAT_API_URL"), opt("CHAT_MODEL")
    return {"url": url, "key": opt("CHAT_API_KEY"), "model": model} if url and model else None


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
              check: Callable[[str], bool] = bool, local: Optional[dict] = None,
              timeout: float = 90.0) -> Optional[str]:
    """The first usable answer: HomeAI, then each OpenAI model in turn."""
    local = local if local is not None else local_provider()
    if local:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=LOCAL_TIMEOUT_S) as client:
                resp = await client.post(
                    local["url"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {local.get('key') or 'none'}",
                             "Content-Type": "application/json"},
                    json={"model": local["model"], "reasoning_effort": "none",
                          "messages": [{"role": "user", "content": prompt}]})
            took = time.monotonic() - t0
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"] or ""
                if check(text):
                    logger.info("%s by HomeAI in %.1f s", label, took)
                    return text
                logger.warning("%s: HomeAI answer not usable after %.1f s (%d characters)",
                               label, took, len(text))
            else:
                logger.warning("%s: HomeAI HTTP %s after %.1f s", label, resp.status_code, took)
        except Exception as e:
            logger.warning("%s: HomeAI failed after %.1f s: %r", label, time.monotonic() - t0, e)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in [m for m in models if m]:
            try:
                resp = await client.post(
                    url, headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"},
                    json={"model": model, "input": prompt})
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
