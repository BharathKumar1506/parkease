"""
websocket.py — Real-time slot updates for ParkEase
===================================================
When any slot changes (booked, held, released), the server pushes the
change instantly to every browser currently viewing that lot.

Frontend connects to:  ws://<host>:8000/ws/slots/<lot_id>
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Tracks all open WebSocket connections grouped by lot_id."""
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, ws: WebSocket, lot_id: str):
        await ws.accept()
        self.connections.setdefault(lot_id, []).append(ws)
        print(f"[WS] connected lot={lot_id} viewers={len(self.connections[lot_id])}")

    def disconnect(self, ws: WebSocket, lot_id: str):
        if lot_id in self.connections:
            try:
                self.connections[lot_id].remove(ws)
            except ValueError:
                pass

    async def broadcast(self, lot_id: str, message: dict):
        """Send a JSON message to everyone watching this lot."""
        key = str(lot_id)
        if key not in self.connections:
            return
        dead = []
        for ws in self.connections[key]:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, key)


manager = ConnectionManager()


@router.websocket("/ws/slots/{lot_id}")
async def slot_socket(ws: WebSocket, lot_id: str):
    await manager.connect(ws, lot_id)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(ws, lot_id)
        print(f"[WS] disconnected lot={lot_id}")


# ── Helper functions other routes call to push updates ──────────────────────
async def push_slot_update(lot_id: int, floor: str, slot_label: str, status: str):
    await manager.broadcast(str(lot_id), {
        "type": "slot_update",
        "lot_id": lot_id,
        "floor": floor,
        "slot_label": slot_label,
        "status": status,
    })


async def push_availability(lot_id: int, available: int):
    await manager.broadcast(str(lot_id), {
        "type": "availability",
        "lot_id": lot_id,
        "available": available,
    })
