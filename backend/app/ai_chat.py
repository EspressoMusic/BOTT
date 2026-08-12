"""Lets the user ask the bot free-text questions about a marked chart zone, a
trade, or just general market opinion — backed by OpenAI's chat API. Everything
else in this app (signals, risk limits, feedback rules) is deterministic
code on purpose; this is the one place that calls out to an LLM, and only to
answer a question — it never places or blocks trades.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "אתה עוזר מסחר שמלווה בוט מסחר אוטומטי במסחר בזהב (XAU/USD). "
    "כל המסחר בפועל הוא מדומה (paper trading) — אין כאן כסף אמיתי בסיכון. "
    "המשתמש עשוי לשאול אותך על אזור שסימן בגרף, על עסקה ספציפית, או שאלה כללית. "
    "תענה בעברית, בקצרה ובפשטות, כמו אדם שמסביר לחבר — בלי ז'רגון מיותר. "
    "אתה יכול לתת דעה מקצועית (למשל האם אזור נראה תמיכה/התנגדות סבירה), "
    "אבל תבהיר כשרלוונטי שזו לא תחליף לייעוץ השקעות אמיתי."
)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured — add it to backend/.env")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _fmt_time(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).strftime("%H:%M")


def build_context(
    zone: dict | None,
    trade: dict | None,
    recent_candles: list[dict],
    recent_thoughts: list[str],
    active_strategy: str,
) -> str:
    parts: list[str] = [f"האסטרטגיה הפעילה כרגע: {active_strategy}."]

    if zone:
        parts.append(
            "המשתמש סימן אזור בגרף: טווח מחירים "
            f"{zone['price_low']:.2f}–{zone['price_high']:.2f}, "
            f"בין השעות {_fmt_time(zone['start_time'])}–{_fmt_time(zone['end_time'])}."
        )

    if trade:
        side = "קנייה" if trade["side"] == "BUY" else "מכירה"
        line = f"עסקה רלוונטית: {side}, כניסה במחיר {trade['entry_price']:.2f}"
        if trade.get("stop_loss") is not None:
            line += f", סטופ לוס {trade['stop_loss']:.2f}"
        if trade.get("take_profit") is not None:
            line += f", טייק פרופיט {trade['take_profit']:.2f}"
        line += f", סטטוס: {'פתוחה' if trade['status'] == 'OPEN' else 'סגורה'}"
        if trade.get("pnl") is not None:
            line += f", רווח/הפסד {trade['pnl']:.2f}$"
        parts.append(line + ".")

    if recent_candles:
        lows = [c["low"] for c in recent_candles]
        highs = [c["high"] for c in recent_candles]
        last_close = recent_candles[-1]["close"]
        parts.append(
            f"נתוני מחיר אחרונים: מחיר נוכחי {last_close:.2f}, "
            f"טווח בזמן האחרון {min(lows):.2f}–{max(highs):.2f}."
        )

    if recent_thoughts:
        parts.append("מחשבות אחרונות של הבוט: " + " | ".join(recent_thoughts[-5:]))

    return "\n".join(parts)


async def ask(question: str, context: str) -> str:
    client = _get_client()
    response = await client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": f"הקשר נוכחי:\n{context}"},
            {"role": "user", "content": question},
        ],
        max_tokens=400,
    )
    reply = response.choices[0].message.content
    return reply.strip() if reply else "לא הצלחתי לנסח תשובה, נסו שוב."
