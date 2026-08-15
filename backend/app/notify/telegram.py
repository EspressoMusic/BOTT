"""Optional trade-opened/closed notifications via a Telegram bot. Off by
default (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID both empty) — best-effort only,
so a slow/unreachable Telegram API never delays or breaks real trading logic.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


async def send_telegram_message(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"{_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
        if resp.status_code >= 400:
            logger.warning("Telegram notification failed: %s %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Telegram notification failed")
