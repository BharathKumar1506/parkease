from fastapi import APIRouter, HTTPException, Header
from database import get_db
from models import AdminLogin, CreateLotRequest, UpdateLotRequest, CreateFloorSlotsRequest
from datetime import datetime, timedelta
import os, secrets

router = APIRouter(prefix="/api/admin", tags=["Admin"])

ADMIN_USER  = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS  = os.getenv("ADMIN_PASSWORD", "parkease2024")

# Simple in-memory token store (replace with Redis/DB for production)
_active_tokens: set = set()

def _verify_token(token: str = Header(None, alias="X-Admin-Token")):
    if not token or token not in _active_tokens:
        raise HTTPException(status_code=401, detail="Unauthorized — invalid or missing token")
    return token

# ── LOGIN ─────────────────────────────────────────────────
@router.post("/login")
async def admin_login(data: AdminLogin):
    if data.username != ADMIN_USER or data.password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(24)
    _active_tokens.add(token)
    return {"success": True, "token": token, "message": "Login successful"}

# ── LOGOUT ────────────────────────────────────────────────
@router.post("/logout")
async def admin_logout(x_admin_token: str = Header(None)):
    _active_tokens.discard(x_admin_token)
    return {"success": True, "message": "Logged out"}

# ── DASHBOARD STATS ───────────────────────────────────────
@router.get("/stats")
async def get_stats(x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db  = get_db()
    now = datetime.utcnow()
    today = datetime(now.year, now.month, now.day)

    total_bookings  = await db.bookings.count_documents({})
    today_bookings  = await db.bookings.count_documents({"created_at": {"$gte": today}})
    active_bookings = await db.bookings.count_documents({"status": "active"})
    cancelled       = await db.bookings.count_documents({"status": "cancelled"})
    total_lots      = await db.lots.count_documents({})
    total_slots     = await db.slots.count_documents({})
    avail_slots     = await db.slots.count_documents({"status": "available"})
    occupied_slots  = await db.slots.count_documents({"status": "occupied"})
    held_slots      = await db.slots.count_documents({"status": "held"})

    # Total revenue
    pipeline = [{"$match": {"status": {"$ne": "cancelled"}}},
                {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}]
    rev = await db.bookings.aggregate(pipeline).to_list(1)
    total_revenue = round(rev[0]["total"], 2) if rev else 0

    # Today revenue
    t_pipeline = [{"$match": {"created_at": {"$gte": today}, "status": {"$ne": "cancelled"}}},
                  {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}]
    t_rev = await db.bookings.aggregate(t_pipeline).to_list(1)
    today_revenue = round(t_rev[0]["total"], 2) if t_rev else 0

    occupancy = round(((total_slots - avail_slots) / total_slots * 100), 1) if total_slots else 0

    return {
        "success": True,
        "stats": {
            "total_bookings":  total_bookings,
            "today_bookings":  today_bookings,
            "active_bookings": active_bookings,
            "cancelled":       cancelled,
            "total_lots":      total_lots,
            "total_slots":     total_slots,
            "available_slots": avail_slots,
            "occupied_slots":  occupied_slots,
            "held_slots":      held_slots,
            "total_revenue":   total_revenue,
            "today_revenue":   today_revenue,
            "occupancy_rate":  occupancy
        }
    }

# ── ALL BOOKINGS ──────────────────────────────────────────
@router.get("/bookings")
async def get_all_bookings(limit: int = 100, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    bookings = await db.bookings.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    for b in bookings:
        b["entry_time"] = b["entry_time"].isoformat()
        b["exit_time"]  = b["exit_time"].isoformat()
        b["created_at"] = b["created_at"].isoformat()
    return {"success": True, "bookings": bookings, "count": len(bookings)}

# ── CANCEL BOOKING (admin) ────────────────────────────────
@router.post("/bookings/{booking_id}/cancel")
async def admin_cancel_booking(booking_id: str, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    booking = await db.bookings.find_one({"booking_id": booking_id.upper()})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    await db.bookings.update_one(
        {"booking_id": booking_id.upper()}, {"$set": {"status": "cancelled"}}
    )
    await db.slots.update_one(
        {"lot_id": booking["lot_id"], "floor": booking["floor"], "slot_label": booking["slot_label"]},
        {"$set": {"status": "available", "booking_id": None}}
    )
    await db.lots.update_one(
        {"lot_id": booking["lot_id"]}, {"$inc": {"available_slots": 1}}
    )
    return {"success": True, "message": f"Booking {booking_id.upper()} cancelled"}

# ── REVENUE BY LOT ────────────────────────────────────────
@router.get("/revenue/by-lot")
async def revenue_by_lot(x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    pipeline = [
        {"$match": {"status": {"$ne": "cancelled"}}},
        {"$group": {
            "_id": {"lot_id": "$lot_id", "lot_name": "$lot_name"},
            "revenue":  {"$sum": "$total_amount"},
            "bookings": {"$sum": 1}
        }},
        {"$sort": {"revenue": -1}}
    ]
    result = await db.bookings.aggregate(pipeline).to_list(50)
    data = [{"lot_id": r["_id"]["lot_id"], "lot_name": r["_id"]["lot_name"],
             "revenue": round(r["revenue"], 2), "bookings": r["bookings"]} for r in result]
    return {"success": True, "revenue_by_lot": data}

# ── MANAGE LOTS ───────────────────────────────────────────
@router.get("/lots")
async def admin_get_lots(x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    lots = await db.lots.find({}, {"_id": 0}).sort("lot_id", 1).to_list(200)
    return {"success": True, "lots": lots}

@router.post("/lots")
async def admin_create_lot(data: CreateLotRequest, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    existing = await db.lots.find_one({"lot_id": data.lot_id})
    if existing:
        raise HTTPException(status_code=409, detail=f"Lot ID {data.lot_id} already exists")
    lot = data.model_dump()
    await db.lots.insert_one(lot)
    lot.pop("_id", None)
    return {"success": True, "lot": lot}

@router.put("/lots/{lot_id}")
async def admin_update_lot(lot_id: int, data: UpdateLotRequest, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    existing = await db.lots.find_one({"lot_id": lot_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Lot not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    await db.lots.update_one({"lot_id": lot_id}, {"$set": updates})
    updated = await db.lots.find_one({"lot_id": lot_id}, {"_id": 0})
    return {"success": True, "lot": updated}

@router.delete("/lots/{lot_id}")
async def admin_delete_lot(lot_id: int, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    existing = await db.lots.find_one({"lot_id": lot_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Lot not found")
    await db.lots.delete_one({"lot_id": lot_id})
    r = await db.slots.delete_many({"lot_id": lot_id})
    return {"success": True, "message": f"Lot {lot_id} and {r.deleted_count} slots deleted"}

# ── MANAGE SLOTS ──────────────────────────────────────────
@router.post("/slots/bulk")
async def admin_create_floor_slots(data: CreateFloorSlotsRequest, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    await db.slots.delete_many({"lot_id": data.lot_id, "floor": data.floor})
    slots = []
    for i in range(1, data.normal_count + 1):
        slots.append({"lot_id": data.lot_id, "floor": data.floor,
                      "slot_label": f"A{i}", "is_premium": False,
                      "status": "available", "booking_id": None,
                      "held_by": None, "held_until": None})
    for i in range(1, data.premium_count + 1):
        slots.append({"lot_id": data.lot_id, "floor": data.floor,
                      "slot_label": f"P{i}", "is_premium": True,
                      "status": "available", "booking_id": None,
                      "held_by": None, "held_until": None})
    if slots:
        await db.slots.insert_many(slots)
    total_avail = await db.slots.count_documents({"lot_id": data.lot_id, "status": "available"})
    await db.lots.update_one({"lot_id": data.lot_id}, {"$set": {"available_slots": total_avail}})
    return {"success": True, "created": len(slots)}

@router.post("/slots/{lot_id}/reset")
async def admin_reset_slots(lot_id: int, x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    result = await db.slots.update_many(
        {"lot_id": lot_id},
        {"$set": {"status": "available", "booking_id": None,
                  "held_by": None, "held_until": None}}
    )
    total = await db.slots.count_documents({"lot_id": lot_id})
    await db.lots.update_one({"lot_id": lot_id}, {"$set": {"available_slots": total}})
    return {"success": True, "reset": result.modified_count}

# ── SEED / CLEAR ──────────────────────────────────────────
@router.post("/seed")
async def admin_seed(x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    count = await db.lots.count_documents({})
    if count > 0:
        return {"success": False, "message": f"DB already has {count} lots"}
    sample_lots = [
        {"lot_id": 1, "name": "City Centre Parking", "address": "MG Road, Tiruppur",
         "city": "Tiruppur", "price_per_hour": 30, "premium_price_per_hour": 50,
         "total_slots": 60, "available_slots": 60, "floors": ["G", "1", "2"],
         "amenities": ["CCTV", "24/7", "EV Charging", "Covered"],
         "image_url": "", "rating": 4.5, "distance": "0.2 km"},
        {"lot_id": 2, "name": "Mall Parking Complex", "address": "Avinashi Road, Tiruppur",
         "city": "Tiruppur", "price_per_hour": 25, "premium_price_per_hour": 45,
         "total_slots": 80, "available_slots": 80, "floors": ["B1", "G", "1"],
         "amenities": ["CCTV", "Lift", "Covered", "Valet"],
         "image_url": "", "rating": 4.2, "distance": "0.5 km"},
        {"lot_id": 3, "name": "Station Road Parking", "address": "Station Road, Tiruppur",
         "city": "Tiruppur", "price_per_hour": 20, "premium_price_per_hour": 35,
         "total_slots": 40, "available_slots": 40, "floors": ["G", "1"],
         "amenities": ["CCTV", "24/7"], "image_url": "", "rating": 3.9, "distance": "1.1 km"},
    ]
    await db.lots.insert_many(sample_lots)
    all_slots = []
    for lot in sample_lots:
        for floor in lot["floors"]:
            for i in range(1, 11):
                all_slots.append({"lot_id": lot["lot_id"], "floor": floor,
                                  "slot_label": f"A{i}", "is_premium": False,
                                  "status": "available", "booking_id": None,
                                  "held_by": None, "held_until": None})
            for i in range(1, 6):
                all_slots.append({"lot_id": lot["lot_id"], "floor": floor,
                                  "slot_label": f"P{i}", "is_premium": True,
                                  "status": "available", "booking_id": None,
                                  "held_by": None, "held_until": None})
    await db.slots.insert_many(all_slots)
    return {"success": True, "lots": len(sample_lots), "slots": len(all_slots)}

@router.delete("/clear")
async def admin_clear_all(x_admin_token: str = Header(None)):
    _verify_token(x_admin_token)
    db = get_db()
    r1 = await db.lots.delete_many({})
    r2 = await db.slots.delete_many({})
    r3 = await db.bookings.delete_many({})
    return {"success": True, "lots": r1.deleted_count,
            "slots": r2.deleted_count, "bookings": r3.deleted_count}


# ════════════════════════════════════════════════════════════════
#  ANALYTICS  (charts data)
# ════════════════════════════════════════════════════════════════
@router.get("/analytics/revenue-trend")
async def revenue_trend(days: int = 7, x_admin_token: str = Header(None)):
    """Revenue + booking count per day for the last N days."""
    _verify_token(x_admin_token)
    db = get_db()
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day) - timedelta(days=days - 1)

    pipeline = [
        {"$match": {"created_at": {"$gte": start}, "status": {"$ne": "cancelled"}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "revenue":  {"$sum": "$total_amount"},
            "bookings": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.bookings.aggregate(pipeline).to_list(100)
    by_day = {r["_id"]: r for r in rows}

    labels, revenue, bookings = [], [], []
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        labels.append(d)
        revenue.append(round(by_day.get(d, {}).get("revenue", 0), 2))
        bookings.append(by_day.get(d, {}).get("bookings", 0))
    return {"success": True, "labels": labels, "revenue": revenue, "bookings": bookings}


@router.get("/analytics/by-hour")
async def bookings_by_hour(x_admin_token: str = Header(None)):
    """Booking counts grouped by hour of day (0-23) — reveals peak hours."""
    _verify_token(x_admin_token)
    db = get_db()
    pipeline = [
        {"$match": {"status": {"$ne": "cancelled"}}},
        {"$group": {"_id": {"$hour": "$entry_time"}, "count": {"$sum": 1}}},
    ]
    rows = await db.bookings.aggregate(pipeline).to_list(50)
    counts = {r["_id"]: r["count"] for r in rows if r["_id"] is not None}
    hours = list(range(24))
    data = [counts.get(h, 0) for h in hours]
    labels = [f"{h:02d}:00" for h in hours]
    return {"success": True, "labels": labels, "counts": data}


@router.get("/analytics/status-breakdown")
async def status_breakdown(x_admin_token: str = Header(None)):
    """Counts of active / expired / cancelled bookings for a pie chart."""
    _verify_token(x_admin_token)
    db = get_db()
    pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    rows = await db.bookings.aggregate(pipeline).to_list(20)
    out = {r["_id"] or "unknown": r["count"] for r in rows}
    return {"success": True, "breakdown": out}


@router.get("/analytics/vehicle-split")
async def vehicle_split(x_admin_token: str = Header(None)):
    """2-wheeler vs 4-wheeler split."""
    _verify_token(x_admin_token)
    db = get_db()
    pipeline = [{"$group": {"_id": "$vehicle_type", "count": {"$sum": 1}}}]
    rows = await db.bookings.aggregate(pipeline).to_list(20)
    out = {(r["_id"] or "Other"): r["count"] for r in rows}
    return {"success": True, "split": out}


# ════════════════════════════════════════════════════════════════
#  USER MANAGEMENT
# ════════════════════════════════════════════════════════════════
def _clean_phone(p: str) -> str:
    return "".join(c for c in (p or "") if c.isdigit())[-10:]

@router.get("/users")
async def list_users(x_admin_token: str = Header(None)):
    """All registered users + their booking count and total spent."""
    _verify_token(x_admin_token)
    db = get_db()

    users = await db.users.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    all_bookings = await db.bookings.find(
        {"status": {"$ne": "cancelled"}},
        {"_id": 0, "user_phone": 1, "total_amount": 1}
    ).to_list(5000)

    # aggregate per phone (digit-normalized)
    agg = {}
    for b in all_bookings:
        ph = _clean_phone(b.get("user_phone", ""))
        if not ph:
            continue
        a_ = agg.setdefault(ph, {"count": 0, "spent": 0.0})
        a_["count"] += 1
        a_["spent"] += b.get("total_amount", 0) or 0

    out = []
    for u in users:
        ph = _clean_phone(u.get("phone", ""))
        stat = agg.get(ph, {"count": 0, "spent": 0.0})
        out.append({
            "user_id":  u.get("user_id", ""),
            "phone":    u.get("phone", ""),
            "name":     u.get("name", "") or "—",
            "email":    u.get("email", "") or "—",
            "bookings": stat["count"],
            "spent":    round(stat["spent"], 2),
            "joined":   u["created_at"].isoformat() if u.get("created_at") and hasattr(u["created_at"], "isoformat") else "",
        })
    out.sort(key=lambda x: x["bookings"], reverse=True)
    return {"success": True, "users": out, "count": len(out)}


@router.get("/users/{phone}/bookings")
async def user_bookings(phone: str, x_admin_token: str = Header(None)):
    """All bookings for one user (digit-normalized match)."""
    _verify_token(x_admin_token)
    db = get_db()
    phone = _clean_phone(phone)
    raw = await db.bookings.find({}, {"_id": 0}).sort("created_at", -1).limit(500).to_list(500)
    bookings = [b for b in raw if _clean_phone(b.get("user_phone", "")) == phone]
    for b in bookings:
        for k in ("entry_time", "exit_time", "created_at"):
            if b.get(k) and hasattr(b[k], "isoformat"):
                b[k] = b[k].isoformat()
    return {"success": True, "bookings": bookings, "count": len(bookings)}


# ════════════════════════════════════════════════════════════════
#  BOOKING SEARCH / FILTER
# ════════════════════════════════════════════════════════════════
@router.get("/bookings/search")
async def search_bookings(
    q: str = "", status: str = "", lot_id: int = -1,
    date_from: str = "", date_to: str = "",
    x_admin_token: str = Header(None)
):
    """Flexible booking search.
    q matches booking_id / phone / vehicle_number / name (case-insensitive)."""
    _verify_token(x_admin_token)
    db = get_db()

    query = {}
    if status:
        query["status"] = status
    if lot_id is not None and lot_id >= 0:
        query["lot_id"] = lot_id
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            rng["$lte"] = datetime.fromisoformat(date_to) + timedelta(days=1)
        query["created_at"] = rng

    raw = await db.bookings.find(query, {"_id": 0}).sort("created_at", -1).limit(500).to_list(500)

    if q:
        ql = q.strip().lower()
        qd = "".join(c for c in q if c.isdigit())
        def hit(b):
            if ql in str(b.get("booking_id", "")).lower(): return True
            if ql in str(b.get("vehicle_number", "")).lower(): return True
            if ql in str(b.get("user_name", "")).lower(): return True
            if qd and qd in "".join(c for c in str(b.get("user_phone", "")) if c.isdigit()): return True
            return False
        raw = [b for b in raw if hit(b)]

    for b in raw:
        for k in ("entry_time", "exit_time", "created_at"):
            if b.get(k) and hasattr(b[k], "isoformat"):
                b[k] = b[k].isoformat()
    return {"success": True, "bookings": raw, "count": len(raw)}
