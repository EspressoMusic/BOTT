from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    manager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            # No client->server messages expected yet; just keep the connection open
            # and detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
