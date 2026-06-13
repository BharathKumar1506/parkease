"""
payments.py — UPI Payment Routes for ParkEase
===============================================
Includes QR-based live session flow:
  POST /api/payments/qr-session   → create a pending QR session (desktop calls this)
  POST /api/payments/qr-confirm   → mobile calls this after tapping Pay Now
  GET  /api/payments/qr-status/{token} → desktop polls this to detect payment
  POST /api/payments/initiate     → legacy (kept for compatibility)
  POST /api/payments/verify       → legacy (kept for compatibility)
  GET  /api/payments/{txn_id}     → look up a payment record
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import random
import string

router = APIRouter(prefix="/api/payments", tags=["Payments"])


# ── Helpers ───────────────────────────────────────────────────────────────────
def gen_txn_id() -> str:
    ts = datetime.utcnow().strftime("%y%m%d")
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"T{ts}{rand}"

def gen_upi_ref() -> str:
    return str(random.randint(600000000000, 699999999999))

def gen_token() -> str:
    return "PE" + "".join(random.choices(string.ascii_uppercase + string.digits, k=14))


# ── Models ────────────────────────────────────────────────────────────────────
class QRSessionRequest(BaseModel):
    amount: float
    lot_name: str
    slot_label: str
    user_name: Optional[str] = ""
    user_phone: Optional[str] = ""

class QRConfirmRequest(BaseModel):
    token: str

class InitiatePaymentRequest(BaseModel):
    amount: float
    lot_name: str
    slot_label: str
    user_name: str
    user_phone: str
    upi_app: Optional[str] = "UPI"

class VerifyPaymentRequest(BaseModel):
    txn_id: str
    upi_id: Optional[str] = ""


# ── QR Session Routes ─────────────────────────────────────────────────────────

@router.post("/qr-session")
async def create_qr_session(data: QRSessionRequest):
    """
    Desktop calls this when UPI QR is shown.
    Creates a pending session with a unique token.
    Returns the token — desktop embeds it in the QR URL and polls /qr-status/{token}.
    """
    from database import get_db
    db = get_db()

    token = gen_token()
    # Ensure uniqueness
    while await db.qr_sessions.find_one({"token": token}):
        token = gen_token()

    doc = {
        "token":      token,
        "amount":     data.amount,
        "lot_name":   data.lot_name,
        "slot_label": data.slot_label,
        "user_name":  data.user_name,
        "user_phone": data.user_phone,
        "status":     "pending",      # pending → paid
        "created_at": datetime.utcnow(),
        "paid_at":    None,
        "txn_id":     None,
        "upi_ref":    None,
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }
    await db.qr_sessions.insert_one(doc)

    return {"success": True, "token": token}


@router.post("/qr-confirm")
async def confirm_qr_payment(data: QRConfirmRequest):
    """
    Mobile calls this after the user taps Pay Now on the mobile page.
    Marks the session as paid so the desktop poll detects it.
    """
    from database import get_db
    db = get_db()

    session = await db.qr_sessions.find_one({"token": data.token})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] == "paid":
        return {"success": True, "message": "Already confirmed"}
    if datetime.utcnow() > session["expires_at"]:
        raise HTTPException(status_code=410, detail="QR session expired")

    txn_id  = gen_txn_id()
    upi_ref = gen_upi_ref()

    await db.qr_sessions.update_one(
        {"token": data.token},
        {"$set": {
            "status":  "paid",
            "paid_at": datetime.utcnow(),
            "txn_id":  txn_id,
            "upi_ref": upi_ref,
        }}
    )

    return {
        "success": True,
        "txn_id":  txn_id,
        "upi_ref": upi_ref,
        "message": "Payment confirmed",
    }


@router.get("/qr-status/{token}")
async def get_qr_status(token: str):
    """
    Desktop polls this every second.
    Returns status: pending | paid | expired
    """
    from database import get_db
    db = get_db()

    session = await db.qr_sessions.find_one({"token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check expiry
    if session["status"] == "pending" and datetime.utcnow() > session["expires_at"]:
        await db.qr_sessions.update_one({"token": token}, {"$set": {"status": "expired"}})
        return {"status": "expired"}

    return {
        "status":  session["status"],
        "txn_id":  session.get("txn_id"),
        "upi_ref": session.get("upi_ref"),
        "amount":  session.get("amount"),
    }


# ── Legacy Routes (kept for compatibility) ────────────────────────────────────

@router.post("/initiate")
async def initiate_payment(data: InitiatePaymentRequest):
    from database import get_db
    db = get_db()
    txn_id = gen_txn_id()
    while await db.payments.find_one({"txn_id": txn_id}):
        txn_id = gen_txn_id()
    doc = {
        "txn_id": txn_id, "amount": data.amount, "lot_name": data.lot_name,
        "slot_label": data.slot_label, "user_name": data.user_name,
        "user_phone": data.user_phone, "upi_app": data.upi_app,
        "status": "pending", "created_at": datetime.utcnow(),
        "verified_at": None, "upi_ref": None,
    }
    await db.payments.insert_one(doc)
    return {"success": True, "txn_id": txn_id, "message": "Payment initiated", "amount": data.amount}


@router.post("/verify")
async def verify_payment(data: VerifyPaymentRequest):
    from database import get_db
    db = get_db()
    payment = await db.payments.find_one({"txn_id": data.txn_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if payment["status"] == "success":
        return {"success": True, "txn_id": data.txn_id, "upi_ref": payment.get("upi_ref", gen_upi_ref()), "message": "Already verified"}
    upi_ref = gen_upi_ref()
    await db.payments.update_one(
        {"txn_id": data.txn_id},
        {"$set": {"status": "success", "verified_at": datetime.utcnow(), "upi_ref": upi_ref, "upi_id": data.upi_id or ""}}
    )
    return {"success": True, "txn_id": data.txn_id, "upi_ref": upi_ref, "message": "Payment verified"}


@router.get("/{txn_id}")
async def get_payment(txn_id: str):
    from database import get_db
    db = get_db()
    payment = await db.payments.find_one({"txn_id": txn_id.upper()}, {"_id": 0})
    if not payment:
        raise HTTPException(status_code=404, detail="Transaction not found")
    payment["created_at"] = payment["created_at"].isoformat()
    if payment.get("verified_at"):
        payment["verified_at"] = payment["verified_at"].isoformat()
    return {"success": True, "payment": payment}
