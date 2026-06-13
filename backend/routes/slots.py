from fastapi import APIRouter, HTTPException
from database import get_db
from models import CreateSlotRequest, CreateFloorSlotsRequest, UpdateSlotStatusRequest
from datetime import datetime, timedelta
from pydantic import BaseModel

router = APIRouter(prefix="/api/slots", tags=["Slots"])

class HoldRequest(BaseModel):
    lot_id: int
    floor: str
    slot_label: str
    user_phone: str

# ── GET slots for a floor ─────────────────────────────────
@router.get("/{lot_id}/{floor}")
async def get_slots(lot_id: int, floor: str):
    db = get_db()
    # Auto-release expired holds
    now = datetime.utcnow()
    await db.slots.update_many(
        {"lot_id": lot_id, "floor": floor, "status": "held", "held_until": {"$lt": now}},
        {"$set": {"status": "available", "held_by": None, "held_until": None}}
    )

    slots = await db.slots.find(
        {"lot_id": lot_id, "floor": floor}, {"_id": 0}
    ).to_list(200)

    section_a = [s for s in slots if not s.get("is_premium", False)]
    section_b = [s for s in slots if s.get("is_premium", False)]
    available  = sum(1 for s in slots if s["status"] == "available")

    return {
        "success": True, "lot_id": lot_id, "floor": floor,
        "section_a": section_a, "section_b": section_b,
        "available": available, "total": len(slots)
    }

# ── GET all slots for a lot ───────────────────────────────
@router.get("/{lot_id}")
async def get_all_slots_for_lot(lot_id: int):
    db = get_db()
    slots = await db.slots.find({"lot_id": lot_id}, {"_id": 0}).to_list(500)
    by_floor = {}
    for s in slots:
        f = s["floor"]
        by_floor.setdefault(f, []).append(s)
    return {"success": True, "lot_id": lot_id, "floors": by_floor, "total": len(slots)}

# ── HOLD a slot ───────────────────────────────────────────
@router.post("/hold")
async def hold_slot(data: HoldRequest):
    db = get_db()
    now = datetime.utcnow()
    slot = await db.slots.find_one({
        "lot_id": data.lot_id, "floor": data.floor, "slot_label": data.slot_label
    })
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot["status"] == "occupied":
        raise HTTPException(status_code=409, detail="Slot already occupied")
    if slot["status"] == "held" and slot.get("held_until") and slot["held_until"] > now:
        raise HTTPException(status_code=409, detail="Slot is currently held by another user")
    if slot["status"] == "maintenance":
        raise HTTPException(status_code=409, detail="Slot is under maintenance")

    held_until = now + timedelta(minutes=2)
    await db.slots.update_one(
        {"lot_id": data.lot_id, "floor": data.floor, "slot_label": data.slot_label},
        {"$set": {"status": "held", "held_by": data.user_phone, "held_until": held_until}}
    )
    try:
        from routes.websocket import push_slot_update
        await push_slot_update(data.lot_id, data.floor, data.slot_label, "held")
    except Exception:
        pass
    return {"success": True, "held_until": held_until.isoformat()}

# ── RELEASE a slot ────────────────────────────────────────
@router.post("/release")
async def release_slot(data: HoldRequest):
    db = get_db()
    await db.slots.update_one(
        {"lot_id": data.lot_id, "floor": data.floor,
         "slot_label": data.slot_label, "held_by": data.user_phone},
        {"$set": {"status": "available", "held_by": None, "held_until": None}}
    )
    try:
        from routes.websocket import push_slot_update
        await push_slot_update(data.lot_id, data.floor, data.slot_label, "available")
    except Exception:
        pass
    return {"success": True}

# ── CREATE single slot ────────────────────────────────────
@router.post("/")
async def create_slot(data: CreateSlotRequest):
    db = get_db()
    existing = await db.slots.find_one({
        "lot_id": data.lot_id, "floor": data.floor, "slot_label": data.slot_label
    })
    if existing:
        raise HTTPException(status_code=409, detail="Slot already exists")
    slot = {**data.model_dump(), "status": "available",
            "booking_id": None, "held_by": None, "held_until": None}
    await db.slots.insert_one(slot)
    slot.pop("_id", None)
    return {"success": True, "slot": slot}

# ── BULK create slots for a floor ────────────────────────
@router.post("/bulk")
async def create_floor_slots(data: CreateFloorSlotsRequest):
    db = get_db()
    # Remove existing slots for this floor first
    await db.slots.delete_many({"lot_id": data.lot_id, "floor": data.floor})

    slots = []
    for i in range(1, data.normal_count + 1):
        slots.append({
            "lot_id": data.lot_id, "floor": data.floor,
            "slot_label": f"A{i}", "is_premium": False,
            "status": "available", "booking_id": None,
            "held_by": None, "held_until": None
        })
    for i in range(1, data.premium_count + 1):
        slots.append({
            "lot_id": data.lot_id, "floor": data.floor,
            "slot_label": f"P{i}", "is_premium": True,
            "status": "available", "booking_id": None,
            "held_by": None, "held_until": None
        })

    if slots:
        await db.slots.insert_many(slots)

    # Update lot available_slots
    total_available = await db.slots.count_documents(
        {"lot_id": data.lot_id, "status": "available"}
    )
    await db.lots.update_one(
        {"lot_id": data.lot_id},
        {"$set": {"available_slots": total_available}}
    )

    return {
        "success": True,
        "message": f"Created {len(slots)} slots for floor {data.floor}",
        "normal": data.normal_count, "premium": data.premium_count
    }

# ── UPDATE slot status (admin) ────────────────────────────
@router.put("/status")
async def update_slot_status(data: UpdateSlotStatusRequest):
    db = get_db()
    if data.status not in ["available", "occupied", "maintenance"]:
        raise HTTPException(status_code=400, detail="Status must be available, occupied, or maintenance")
    slot = await db.slots.find_one({
        "lot_id": data.lot_id, "floor": data.floor, "slot_label": data.slot_label
    })
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    await db.slots.update_one(
        {"lot_id": data.lot_id, "floor": data.floor, "slot_label": data.slot_label},
        {"$set": {"status": data.status, "held_by": None, "held_until": None}}
    )
    # Update lot available count
    total_available = await db.slots.count_documents(
        {"lot_id": data.lot_id, "status": "available"}
    )
    await db.lots.update_one(
        {"lot_id": data.lot_id}, {"$set": {"available_slots": total_available}}
    )
    return {"success": True, "message": f"Slot {data.slot_label} set to {data.status}"}

# ── RESET all slots for a lot to available ────────────────
@router.post("/{lot_id}/reset")
async def reset_lot_slots(lot_id: int):
    db = get_db()
    result = await db.slots.update_many(
        {"lot_id": lot_id},
        {"$set": {"status": "available", "booking_id": None,
                  "held_by": None, "held_until": None}}
    )
    total = await db.slots.count_documents({"lot_id": lot_id})
    await db.lots.update_one({"lot_id": lot_id}, {"$set": {"available_slots": total}})
    return {
        "success": True,
        "message": f"Reset {result.modified_count} slots to available"
    }

# ── DELETE all slots for a floor ──────────────────────────
@router.delete("/{lot_id}/{floor}")
async def delete_floor_slots(lot_id: int, floor: str):
    db = get_db()
    result = await db.slots.delete_many({"lot_id": lot_id, "floor": floor})
    total_available = await db.slots.count_documents({"lot_id": lot_id, "status": "available"})
    await db.lots.update_one({"lot_id": lot_id}, {"$set": {"available_slots": total_available}})
    return {
        "success": True,
        "message": f"Deleted {result.deleted_count} slots from floor {floor}"
    }
