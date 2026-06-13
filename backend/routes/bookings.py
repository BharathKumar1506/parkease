from fastapi import APIRouter, HTTPException
from database import get_db
from models import CreateBookingRequest
from datetime import datetime
import random, string

router = APIRouter(prefix="/api/bookings", tags=["Bookings"])

def generate_booking_id():
    chars = string.ascii_uppercase + string.digits
    return "PE-" + "".join(random.choices(chars, k=8))

@router.post("/create")
async def create_booking(data: CreateBookingRequest):
    db = get_db()

    # Generate unique booking ID
    booking_id = generate_booking_id()
    while await db.bookings.find_one({"booking_id": booking_id}):
        booking_id = generate_booking_id()

    # Parse times
    try:
        entry_time = datetime.fromisoformat(data.entry_time.replace("Z", "+00:00"))
        exit_time  = datetime.fromisoformat(data.exit_time.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if exit_time <= entry_time:
        raise HTTPException(status_code=400, detail="Exit must be after entry")

    clean_label = data.slot_label.replace(" (Premium)", "").strip()

    # ── Atomically claim the slot (prevents double-booking) ──
    # Only succeeds if the slot is currently available OR held by this same user.
    claimed = await db.slots.find_one_and_update(
        {
            "lot_id": data.lot_id,
            "floor": data.floor,
            "slot_label": clean_label,
            "$or": [
                {"status": "available"},
                {"status": {"$exists": False}},
                {"status": "held", "held_by": data.user_phone},
            ],
        },
        {"$set": {"status": "occupied", "held_by": None, "held_until": None}},
    )
    if claimed is None:
        # Slot is already occupied or held by someone else
        raise HTTPException(
            status_code=409,
            detail="This slot was just booked by someone else. Please pick another slot."
        )

    # Save booking
    booking = {
        "booking_id":     booking_id,
        "lot_id":         data.lot_id,
        "lot_name":       data.lot_name,
        "floor":          data.floor,
        "slot_label":     data.slot_label.replace(" (Premium)", "").strip(),
        "is_premium":     data.is_premium,
        "user_name":      data.user_name,
        "user_phone":     data.user_phone,
        "user_email":     data.user_email or "",
        "vehicle_number": data.vehicle_number,
        "vehicle_type":   data.vehicle_type,
        "vehicle_model":  data.vehicle_model or "",
        "entry_time":     entry_time,
        "exit_time":      exit_time,
        "hours":          data.hours,
        "total_amount":   data.total_amount,
        "promo_code":     data.promo_code or "",
        "discount":       data.discount or 0,
        "payment_method": data.payment_method,
        "upi_txn_id":     data.upi_txn_id or "",   # from dummy UPI flow
        "upi_ref":        data.upi_ref or "",       # bank ref from dummy UPI flow
        "status":         "active",
        "created_at":     datetime.utcnow()
    }
    await db.bookings.insert_one(booking)

    # Attach booking_id to the slot we already claimed above
    await db.slots.update_one(
        {"lot_id": data.lot_id, "floor": data.floor, "slot_label": clean_label},
        {"$set": {"status": "occupied", "booking_id": booking_id, "held_by": None, "held_until": None}}
    )

    # Update lot available count
    await db.lots.update_one(
        {"lot_id": data.lot_id},
        {"$inc": {"available_slots": -1}}
    )

    # ── Real-time: push slot change to everyone viewing this lot ──
    try:
        from routes.websocket import push_slot_update, push_availability
        clean_label = data.slot_label.replace(" (Premium)", "").strip()
        await push_slot_update(data.lot_id, data.floor, clean_label, "occupied")
        lot_now = await db.lots.find_one({"lot_id": data.lot_id})
        if lot_now:
            await push_availability(data.lot_id, lot_now.get("available_slots", 0))
    except Exception:
        pass

    return {
        "success":    True,
        "booking_id": booking_id,
        "message":    "Booking confirmed"
    }

@router.get("/{booking_id}")
async def get_booking(booking_id: str):
    db = get_db()
    booking = await db.bookings.find_one(
        {"booking_id": booking_id.upper()},
        {"_id": 0}
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Auto-expire if past exit time
    now = datetime.utcnow()
    if booking["status"] == "active" and booking["exit_time"] < now:
        await db.bookings.update_one(
            {"booking_id": booking_id.upper()},
            {"$set": {"status": "expired"}}
        )
        booking["status"] = "expired"
        await db.slots.update_one(
            {"lot_id": booking["lot_id"], "floor": booking["floor"], "slot_label": booking["slot_label"]},
            {"$set": {"status": "available", "booking_id": None}}
        )
        await db.lots.update_one(
            {"lot_id": booking["lot_id"]},
            {"$inc": {"available_slots": 1}}
        )

    booking["entry_time"] = booking["entry_time"].isoformat()
    booking["exit_time"]  = booking["exit_time"].isoformat()
    booking["created_at"] = booking["created_at"].isoformat()

    return {"success": True, "booking": booking}

@router.post("/{booking_id}/cancel")
async def cancel_booking(booking_id: str):
    db = get_db()
    booking = await db.bookings.find_one({"booking_id": booking_id.upper()})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    await db.bookings.update_one(
        {"booking_id": booking_id.upper()},
        {"$set": {"status": "cancelled"}}
    )
    await db.slots.update_one(
        {"lot_id": booking["lot_id"], "floor": booking["floor"], "slot_label": booking["slot_label"]},
        {"$set": {"status": "available", "booking_id": None}}
    )
    await db.lots.update_one(
        {"lot_id": booking["lot_id"]},
        {"$inc": {"available_slots": 1}}
    )
    try:
        from routes.websocket import push_slot_update, push_availability
        await push_slot_update(booking["lot_id"], booking["floor"], booking["slot_label"], "available")
        lot_now = await db.lots.find_one({"lot_id": booking["lot_id"]})
        if lot_now:
            await push_availability(booking["lot_id"], lot_now.get("available_slots", 0))
    except Exception:
        pass
    return {"success": True, "message": "Booking cancelled"}
