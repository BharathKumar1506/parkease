from fastapi import APIRouter, HTTPException
from database import get_db
from models import CreateLotRequest, UpdateLotRequest

router = APIRouter(prefix="/api/lots", tags=["Lots"])

# ── GET all lots ──────────────────────────────────────────
@router.get("/")
async def get_all_lots():
    db = get_db()
    lots = await db.lots.find({}, {"_id": 0}).to_list(200)
    return {"success": True, "lots": lots}

# ── GET lots by city ──────────────────────────────────────
@router.get("/city/{city}")
async def get_lots_by_city(city: str):
    db = get_db()
    lots = await db.lots.find(
        {"city": {"$regex": city, "$options": "i"}}, {"_id": 0}
    ).to_list(100)
    return {"success": True, "lots": lots, "city": city}

# ── GET single lot ────────────────────────────────────────
@router.get("/{lot_id}")
async def get_lot(lot_id: int):
    db = get_db()
    lot = await db.lots.find_one({"lot_id": lot_id}, {"_id": 0})
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    return {"success": True, "lot": lot}

# ── CREATE lot ────────────────────────────────────────────
@router.post("/")
async def create_lot(data: CreateLotRequest):
    db = get_db()
    existing = await db.lots.find_one({"lot_id": data.lot_id})
    if existing:
        raise HTTPException(status_code=409, detail=f"Lot with ID {data.lot_id} already exists")
    lot = data.model_dump()
    await db.lots.insert_one(lot)
    lot.pop("_id", None)
    return {"success": True, "lot": lot, "message": "Lot created successfully"}

# ── UPDATE lot ────────────────────────────────────────────
@router.put("/{lot_id}")
async def update_lot(lot_id: int, data: UpdateLotRequest):
    db = get_db()
    existing = await db.lots.find_one({"lot_id": lot_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Lot not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.lots.update_one({"lot_id": lot_id}, {"$set": updates})
    updated = await db.lots.find_one({"lot_id": lot_id}, {"_id": 0})
    return {"success": True, "lot": updated, "message": "Lot updated"}

# ── DELETE lot ────────────────────────────────────────────
@router.delete("/{lot_id}")
async def delete_lot(lot_id: int):
    db = get_db()
    existing = await db.lots.find_one({"lot_id": lot_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Lot not found")
    await db.lots.delete_one({"lot_id": lot_id})
    await db.slots.delete_many({"lot_id": lot_id})
    return {"success": True, "message": f"Lot {lot_id} and all its slots deleted"}

# ── SEED sample lots ──────────────────────────────────────
@router.post("/seed/sample")
async def seed_sample_lots():
    db = get_db()
    count = await db.lots.count_documents({})
    if count > 0:
        return {"success": False, "message": f"Database already has {count} lots. Clear first."}

    sample_lots = [
        {
            "lot_id": 1, "name": "City Centre Parking", "address": "MG Road, Tiruppur",
            "city": "Tiruppur", "price_per_hour": 30, "premium_price_per_hour": 50,
            "total_slots": 60, "available_slots": 60,
            "floors": ["G", "1", "2"],
            "amenities": ["CCTV", "24/7", "EV Charging", "Covered"],
            "image_url": "", "rating": 4.5, "distance": "0.2 km"
        },
        {
            "lot_id": 2, "name": "Mall Parking Complex", "address": "Avinashi Road, Tiruppur",
            "city": "Tiruppur", "price_per_hour": 25, "premium_price_per_hour": 45,
            "total_slots": 80, "available_slots": 80,
            "floors": ["B1", "G", "1"],
            "amenities": ["CCTV", "Lift", "Covered", "Valet"],
            "image_url": "", "rating": 4.2, "distance": "0.5 km"
        },
        {
            "lot_id": 3, "name": "Station Road Parking", "address": "Station Road, Tiruppur",
            "city": "Tiruppur", "price_per_hour": 20, "premium_price_per_hour": 35,
            "total_slots": 40, "available_slots": 40,
            "floors": ["G", "1"],
            "amenities": ["CCTV", "24/7"],
            "image_url": "", "rating": 3.9, "distance": "1.1 km"
        },
    ]

    await db.lots.insert_many(sample_lots)

    # Auto-create slots for each lot
    all_slots = []
    for lot in sample_lots:
        for floor in lot["floors"]:
            for i in range(1, 11):
                all_slots.append({
                    "lot_id": lot["lot_id"], "floor": floor,
                    "slot_label": f"A{i}", "is_premium": False,
                    "status": "available", "booking_id": None,
                    "held_by": None, "held_until": None
                })
            for i in range(1, 6):
                all_slots.append({
                    "lot_id": lot["lot_id"], "floor": floor,
                    "slot_label": f"P{i}", "is_premium": True,
                    "status": "available", "booking_id": None,
                    "held_by": None, "held_until": None
                })

    await db.slots.insert_many(all_slots)
    return {
        "success": True,
        "message": f"Seeded {len(sample_lots)} lots and {len(all_slots)} slots"
    }

# ── CLEAR all lots ────────────────────────────────────────
@router.delete("/seed/clear")
async def clear_all_lots():
    db = get_db()
    r1 = await db.lots.delete_many({})
    r2 = await db.slots.delete_many({})
    return {
        "success": True,
        "message": f"Deleted {r1.deleted_count} lots and {r2.deleted_count} slots"
    }
