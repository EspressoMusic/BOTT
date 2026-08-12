"""Tracks connected WebSocket clients and broadcasts typed JSON messages to all of them."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WS client connected (%d total)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WS client disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message)
        async with self._lock:
            connections = list(self._connections)

        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
