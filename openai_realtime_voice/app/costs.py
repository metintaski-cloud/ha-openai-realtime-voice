"""
OpenAI spending report for the voice assistant.

Uses the official Costs API (GET /v1/organization/costs). That endpoint needs an
Admin key; a restricted Admin key with only read access to the Usage API is enough
and cannot change anything in the account. OpenAI has no API for the prepaid credit
balance, so instead the report compares this month's spending with a monthly budget
(Metin's auto recharge limit, 20 US dollars by default, set in the add-on options).
OpenAI reports costs with some delay, so today's number is approximate.
"""
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COSTS_URL = "https://api.openai.com/v1/organization/costs"

COSTS_TOOL = {
    "type": "function",
    "name": "openai_kosten",
    "description": (
        "Returns the OpenAI API spending in US dollars: today, yesterday, the last 7 days, "
        "this month and last month, plus the monthly budget and how much of it is left. "
        "Call this whenever the user asks about OpenAI costs, usage, spending, bill, "
        "balance or credit (Guthaben, Kosten, Verbrauch, bakiye, harcama)."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

COSTS_BACKEND_HINT = (
    " If the user asks about OpenAI costs, usage, credit, budget or balance, call openai_kosten "
    "and answer briefly in the user's language. Amounts are US dollars; round to cents. "
    "For credit or balance questions say how much of the monthly budget is used and left "
    "(the budget is the monthly auto recharge limit). Today's value can lag a few hours."
)


def _utc_ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def bucket_totals(pages: list[dict]) -> dict[date, float]:
    """Sum the cost results of all buckets per UTC day."""
    totals: dict[date, float] = {}
    for page in pages:
        for bucket in page.get("data") or []:
            start = bucket.get("start_time")
            if start is None:
                continue
            day = datetime.fromtimestamp(int(start), timezone.utc).date()
            for res in bucket.get("results") or []:
                amount = (res.get("amount") or {}).get("value")
                try:
                    totals[day] = totals.get(day, 0.0) + float(amount or 0.0)
                except (TypeError, ValueError):
                    continue
    return totals


def summarize(totals: dict[date, float], today: date, monthly_budget: float = 0.0) -> dict:
    def total(start: date, end: date) -> float:
        return sum(v for d, v in totals.items() if start <= d < end)

    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    tomorrow = today + timedelta(days=1)
    result = {
        "currency": "USD",
        "today": round(total(today, tomorrow), 2),
        "yesterday": round(total(today - timedelta(days=1), today), 2),
        "last_7_days": round(total(today - timedelta(days=6), tomorrow), 2),
        "this_month": round(total(month_start, tomorrow), 2),
        "last_month": round(total(last_month_start, month_start), 2),
        "note": "Costs are reported by OpenAI with a delay of a few hours.",
    }
    if monthly_budget and monthly_budget > 0:
        used = result["this_month"]
        result["monthly_budget"] = round(monthly_budget, 2)
        result["budget_left_this_month"] = round(max(0.0, monthly_budget - used), 2)
        result["budget_used_percent"] = round(100.0 * used / monthly_budget)
        result["budget_note"] = ("Budget = monthly auto recharge limit; the current prepaid "
                                 "balance is not available via API.")
    return result


async def fetch_pages(admin_key: str, start: date, url: str = COSTS_URL,
                      max_pages: int = 5) -> list[dict]:
    pages: list[dict] = []
    params = {"start_time": _utc_ts(start), "bucket_width": "1d", "limit": 180}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for _ in range(max_pages):
            resp = await client.get(url, params=params,
                                    headers={"Authorization": f"Bearer {admin_key}"})
            if resp.status_code != 200:
                raise RuntimeError(f"Costs API HTTP {resp.status_code}: {resp.text[:200]}")
            page = resp.json()
            pages.append(page)
            if not page.get("has_more") or not page.get("next_page"):
                break
            params["page"] = page["next_page"]
    return pages


async def cost_report(admin_key: str, monthly_budget: float = 0.0,
                      url: Optional[str] = None, today: Optional[date] = None) -> dict:
    """Fetch costs and return a short summary dict for the voice assistant."""
    if not admin_key:
        return {"error": "No OpenAI admin key configured."}
    today = today or datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)
    start = (month_start - timedelta(days=1)).replace(day=1)
    start = min(start, today - timedelta(days=6))
    t0 = time.monotonic()
    url = url or os.environ.get("OPENAI_COSTS_URL") or COSTS_URL
    pages = await fetch_pages(admin_key, start, url=url)
    report = summarize(bucket_totals(pages), today, monthly_budget)
    logger.info("Costs report in %.1fs: %s", time.monotonic() - t0, report)
    return report


def _env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return "" if value.lower() == "null" else value


def config_from_env() -> tuple[str, float]:
    key = _env("OPENAI_ADMIN_KEY")
    try:
        budget = float(_env("MONTHLY_BUDGET_USD").replace(",", ".") or 0)
    except ValueError:
        budget = 0.0
    return key, budget
