"""Lets the user ask the bot free-text questions about a marked chart zone, a
trade, or just general market opinion — backed by OpenAI's chat API. Almost
everything else in this app (signals, risk limits, feedback rules) is
deterministic code on purpose; the one deliberate exception is
`set_direction_bias`/`clear_direction_bias` below, which the model can invoke
as a schema-validated tool call (never free text) so the user can tell the
bot in plain Hebrew to wait for a specific side — the model only ever
*requests* the change via a structured, enum-constrained argument; the actual
state mutation happens in the caller's tool_executor (see app/api/chat.py),
never inside this module or the model itself.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "אתה עוזר מסחר שמלווה בוט מסחר אוטומטי במסחר בזהב (XAU/USD). "
    "המשתמש עשוי לשאול אותך על אזור שסימן בגרף, על עסקה ספציפית, על עסקאות אחרונות "
    "שהבוט לקח (כולל דפוסים כמו כמה עסקאות מפסידות באותו טווח מחירים), או שאלה כללית "
    "על השוק. תמיד תתבסס על הנתונים שמופיעים ב'הקשר נוכחי' למטה — אלה נתונים אמיתיים "
    "מהבוט ומהגרף, לא דוגמאות. אם משהו לא מופיע בהקשר, תגיד שאין לך את הנתון הזה "
    "במקום להמציא. "
    "תענה קצר, מדויק ולעניין — כמו הודעת וואטסאפ לחבר, לא כמו דוח. 1-3 משפטים, "
    "לא יותר. אסור: רשימות ממוספרות, כותרות, חלוקה לכמה פסקאות, הקדמות מיותרות "
    "('נשמע ש...', 'זה יכול לקרות ממגוון סיבות...'). תיכנס ישר לעניין. "
    "כשהשאלה נוגעת לעסקאות ספציפיות — תן את המספרים הרלוונטיים מההקשר (מחיר כניסה/יציאה, "
    "רווח/הפסד) ממש במשפט הראשון, בלי לפרט את כל השאר — למשל: 'שתי הקניות ב-4378.02 "
    "ו-4378.67 יצאו בסטופ לוס, הפסד של כ-25-28$ כל אחת — נראה שהאזור הזה שימש התנגדות.' "
    "אם אין לך תשובה קצרה טובה, תגיד את זה בקצרה במקום להאריך. אתה יכול לתת דעה מקצועית "
    "(למשל האם אזור נראה תמיכה/התנגדות), אבל בלי הרצאה — ורק כשממש רלוונטי, תזכיר "
    "בקצרה שזו לא תחליף לייעוץ השקעות אמיתי. "
    "יש לך גם יכולת אמיתית להשפיע על הבוט: אם המשתמש מבקש במפורש שהבוט יחכה לכיוון "
    "מסוים (למשל 'תתכונן לקנייה במקום מכירה', 'רק תמכור עכשיו', 'תחכה לירידה') — תפעיל "
    "את הכלי set_direction_bias עם הכיוון המבוקש. זה חוסם בפועל כל איתות בכיוון ההפוך "
    "עד שנפתחת עסקה בכיוון שביקשו, ואז מתבטל אוטומטית. אם המשתמש מבקש לבטל הנחיה כזו "
    "('תשחרר', 'תפסיק לחכות', 'תחזור לפעול רגיל') — תפעיל את clear_direction_bias. "
    "אל תפעיל אף כלי על סמך שאלת מידע רגילה או ניחוש — רק כשהבקשה לשינוי התנהגות ברורה."
)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_direction_bias",
            "description": (
                "חוסם זמנית איתותי מסחר בכיוון ההפוך לזה שהמשתמש ביקש, עד שנפתחת עסקה "
                "בכיוון המבוקש — ואז החסימה מתבטלת אוטומטית. השתמש רק כשהמשתמש מבקש "
                "במפורש לכוון/לשנות את כיוון המסחר הבא."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "הכיוון שהמשתמש רוצה שהבוט יחכה לו (BUY=קנייה, SELL=מכירה)",
                    }
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_direction_bias",
            "description": "מבטל חסימת כיוון קודמת שנקבעה דרך הצ'אט ומחזיר את הבוט לפעול רגיל בשני הכיוונים.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured — add it to backend/.env")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


_EXIT_REASON_HE = {"SL": "סטופ לוס", "TP": "טייק פרופיט", "MANUAL": "סגירה ידנית"}


def _fmt_time(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).strftime("%H:%M")


def _fmt_datetime(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).strftime("%d/%m %H:%M")


def build_context(
    zone: dict | None,
    trade: dict | None,
    recent_candles: list[dict],
    recent_thoughts: list[str],
    active_strategy: str,
    recent_trades: list[dict] | None = None,
    open_trades: list[dict] | None = None,
    direction_bias: str | None = None,
) -> str:
    parts: list[str] = [f"האסטרטגיה הפעילה כרגע: {active_strategy}."]

    if direction_bias:
        wanted = "קנייה" if direction_bias == "BUY" else "מכירה"
        parts.append(
            f"מצב נוכחי: הבוט חוסם כרגע איתותים שאינם {wanted} (הנחיה קודמת מהצ'אט) — "
            f"ממתין לעסקת {wanted} כדי לבטל את החסימה אוטומטית."
        )

    if zone:
        parts.append(
            "המשתמש סימן אזור בגרף: טווח מחירים "
            f"{zone['price_low']:.2f}–{zone['price_high']:.2f}, "
            f"בין השעות {_fmt_time(zone['start_time'])}–{_fmt_time(zone['end_time'])}."
        )

    if trade:
        side = "קנייה" if trade["side"] == "BUY" else "מכירה"
        line = f"עסקה רלוונטית שהמשתמש בחר: {side}, כניסה במחיר {trade['entry_price']:.2f}"
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

    if recent_trades:
        lines = []
        for t in recent_trades:
            side = "קנייה" if t["side"] == "BUY" else "מכירה"
            reason = _EXIT_REASON_HE.get(t.get("exit_reason") or "", t.get("exit_reason") or "לא ידוע")
            pnl = t.get("pnl") or 0.0
            entry = t["entry_price"]
            exit_price = t.get("exit_price")
            line = f"- {_fmt_datetime(t['time'])} | {t.get('strategy_id', '')}: {side}, כניסה {entry:.2f}"
            if exit_price is not None:
                line += f", יציאה {exit_price:.2f} ({reason})"
            line += f", רווח/הפסד {pnl:+.2f}$"
            if t.get("signal_reason"):
                line += f" — סיבת הכניסה: {t['signal_reason']}"
            lines.append(line)
        parts.append("עסקאות אחרונות שנסגרו (מהחדשה לישנה):\n" + "\n".join(lines))

    if open_trades:
        lines = []
        for t in open_trades:
            side = "קנייה" if t["side"] == "BUY" else "מכירה"
            lines.append(
                f"- {side}, כניסה {t['entry_price']:.2f}, סטופ {t.get('stop_loss')}, טייק {t.get('take_profit')}"
            )
        parts.append("עסקאות פתוחות כרגע:\n" + "\n".join(lines))

    return "\n".join(parts)


async def ask(
    question: str,
    context: str,
    history: list[dict[str, str]] | None = None,
    tool_executor: Callable[[str, dict], str] | None = None,
) -> str:
    """`tool_executor(name, args) -> result_text` is called synchronously for
    each tool call the model requests (see _TOOLS) — it's the only thing in
    this module allowed to actually change bot state, and only in response to
    a schema-validated call, never by parsing the model's free-text reply.
    When the model calls a tool, its result is fed back for a short follow-up
    completion so the reply to the user reflects what actually happened.
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "system", "content": f"הקשר נוכחי:\n{context}"},
        *(history or []),
        {"role": "user", "content": question},
    ]
    response = await client.chat.completions.create(
        model=_MODEL, messages=messages, max_tokens=220, tools=_TOOLS if tool_executor else None
    )
    choice = response.choices[0].message

    if choice.tool_calls and tool_executor is not None:
        messages.append(
            {
                "role": "assistant",
                "content": choice.content,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in choice.tool_calls
                ],
            }
        )
        for call in choice.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result_text = tool_executor(call.function.name, args)
            except Exception as exc:  # tool execution must never crash the chat turn
                logger.exception("Chat tool %s failed", call.function.name)
                result_text = f"שגיאה בביצוע הפעולה: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

        followup = await client.chat.completions.create(model=_MODEL, messages=messages, max_tokens=220)
        reply = followup.choices[0].message.content
        return reply.strip() if reply else "בוצע."

    reply = choice.content
    return reply.strip() if reply else "לא הצלחתי לנסח תשובה, נסו שוב."
