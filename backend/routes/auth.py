"""
auth.py — Phone OTP Login for ParkEase (DEMO MODE)
===================================================
Demo OTP: a real 6-digit code is generated, stored with expiry, and verified
properly. For the demo it is returned in the response / printed to the server
console instead of being sent by SMS. Swapping in a real SMS provider later
only means replacing the one "send" line in send_otp().

Endpoints:
  POST /api/auth/send-otp        → generate + store OTP (returns it in demo mode)
  POST /api/auth/verify-otp      → verify OTP, create/find user, return token
  GET  /api/auth/profile/{phone} → user details + recent bookings
  PUT  /api/auth/profile         → update name/email
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import random, string, hashlib

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Set False later when a real SMS provider is wired in
DEMO_MODE = True


# ── helpers ───────────────────────────────────────────────────────────────────
def gen_otp() -> str:
    return f"{random.randint(0, 999999):06d}"

def hash_otp(otp: str, phone: str) -> str:
    return hashlib.sha256(f"{otp}:{phone}:parkease".encode()).hexdigest()

def gen_user_id() -> str:
    return "U" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def gen_token(user_id: str, phone: str) -> str:
    raw = f"{user_id}:{phone}:{datetime.utcnow().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]

def clean_phone(p: str) -> str:
    return "".join(c for c in p if c.isdigit())[-10:]


# ── models ──────────────────────────────────────────────────────────────────--
class SendOTP(BaseModel):
    phone: str

class VerifyOTP(BaseModel):
    phone: str
    otp: str

class UpdateProfile(BaseModel):
    phone: str
    name: Optional[str] = ""
    email: Optional[str] = ""


# ── routes ──────────────────────────────────────────────────────────────────--
@router.post("/send-otp")
async def send_otp(data: SendOTP):
    from database import get_db
    db = get_db()

    phone = clean_phone(data.phone)
    if len(phone) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit phone number")

    otp = gen_otp()
    await db.otps.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "otp_hash": hash_otp(otp, phone),
            "expires_at": datetime.utcnow() + timedelta(minutes=5),
            "attempts": 0,
            "created_at": datetime.utcnow(),
        }},
        upsert=True,
    )

    # DEMO: print to server console + return in response.
    # REAL SMS later: replace this block with provider.send(phone, otp)
    print(f"[ParkEase OTP] phone={phone} otp={otp}  (demo mode)")

    resp = {"success": True, "message": "OTP sent", "expires_in": 300}
    if DEMO_MODE:
        resp["demo_otp"] = otp   # shown on screen for the demo
    return resp


@router.post("/verify-otp")
async def verify_otp(data: VerifyOTP):
    from database import get_db
    db = get_db()

    phone = clean_phone(data.phone)
    rec = await db.otps.find_one({"phone": phone})
    if not rec:
        raise HTTPException(status_code=400, detail="No OTP found. Please request a new one.")
    if datetime.utcnow() > rec["expires_at"]:
        await db.otps.delete_one({"phone": phone})
        raise HTTPException(status_code=410, detail="OTP expired. Please request a new one.")
    if rec.get("attempts", 0) >= 5:
        await db.otps.delete_one({"phone": phone})
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new OTP.")
    if rec["otp_hash"] != hash_otp(data.otp.strip(), phone):
        await db.otps.update_one({"phone": phone}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=401, detail="Incorrect OTP. Try again.")

    # OTP correct — consume it
    await db.otps.delete_one({"phone": phone})

    # find or create user
    user = await db.users.find_one({"phone": phone}, {"_id": 0})
    is_new = False
    if not user:
        user = {
            "user_id": gen_user_id(),
            "phone": phone,
            "name": "",
            "email": "",
            "created_at": datetime.utcnow(),
        }
        await db.users.insert_one(dict(user))
        is_new = True

    token = gen_token(user["user_id"], phone)

    return {
        "success": True,
        "is_new_user": is_new,
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "phone": phone,
            "name": user.get("name", ""),
            "email": user.get("email", ""),
        },
    }


@router.get("/profile/{phone}")
async def profile(phone: str):
    from database import get_db
    db = get_db()
    phone = clean_phone(phone)

    user = await db.users.find_one({"phone": phone}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("created_at"):
        user["created_at"] = user["created_at"].isoformat()

    # Match by digits-only so "88380 50634", "+918838050634", "8838050634" all match
    raw = await db.bookings.find({}, {"_id": 0}).sort("created_at", -1).limit(500).to_list(500)
    bookings = [b for b in raw if clean_phone(b.get("user_phone", "")) == phone]
    for b in bookings:
        for k in ("entry_time", "exit_time", "created_at"):
            if b.get(k) and hasattr(b[k], "isoformat"):
                b[k] = b[k].isoformat()

    return {"success": True, "user": user, "bookings": bookings, "count": len(bookings)}


@router.put("/profile")
async def update_profile(data: UpdateProfile):
    from database import get_db
    db = get_db()
    phone = clean_phone(data.phone)
    await db.users.update_one(
        {"phone": phone},
        {"$set": {"name": data.name or "", "email": data.email or ""}},
    )
    return {"success": True, "message": "Profile updated"}


# ── Cross-device QR login (WhatsApp-Web style) ────────────────────────────────
def gen_login_token() -> str:
    return "LGN" + "".join(random.choices(string.ascii_uppercase + string.digits, k=14))

class LoginSession(BaseModel):
    phone: str

class LoginVerify(BaseModel):
    token: str
    otp: str


@router.post("/login-session")
async def login_session(data: LoginSession):
    """Desktop calls this after entering phone. Creates a pending login session
    + a demo OTP. Desktop shows the OTP and a QR, then polls /login-status."""
    from database import get_db
    db = get_db()

    phone = clean_phone(data.phone)
    if len(phone) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit phone number")

    token = gen_login_token()
    while await db.login_sessions.find_one({"token": token}):
        token = gen_login_token()

    otp = gen_otp()
    await db.login_sessions.insert_one({
        "token": token,
        "phone": phone,
        "otp_hash": hash_otp(otp, phone),
        "status": "pending",            # pending -> verified
        "attempts": 0,
        "user": None,
        "auth_token": None,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=5),
    })

    print(f"[ParkEase LOGIN] phone={phone} otp={otp} token={token} (demo)")

    resp = {"success": True, "token": token, "expires_in": 300}
    if DEMO_MODE:
        resp["demo_otp"] = otp
    return resp


@router.post("/login-verify")
async def login_verify(data: LoginVerify):
    """Mobile calls this after scanning the QR and entering the OTP."""
    from database import get_db
    db = get_db()

    sess = await db.login_sessions.find_one({"token": data.token})
    if not sess:
        raise HTTPException(status_code=404, detail="Login session not found")
    if sess["status"] == "verified":
        return {"success": True, "message": "Already verified"}
    if datetime.utcnow() > sess["expires_at"]:
        raise HTTPException(status_code=410, detail="Login QR expired. Refresh and try again.")
    if sess.get("attempts", 0) >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts. Refresh the QR.")
    if sess["otp_hash"] != hash_otp(data.otp.strip(), sess["phone"]):
        await db.login_sessions.update_one({"token": data.token}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=401, detail="Incorrect OTP. Try again.")

    # OTP correct — find or create the user
    phone = sess["phone"]
    user = await db.users.find_one({"phone": phone}, {"_id": 0})
    is_new = False
    if not user:
        user = {"user_id": gen_user_id(), "phone": phone, "name": "", "email": "",
                "created_at": datetime.utcnow()}
        await db.users.insert_one(dict(user))
        is_new = True

    auth_token = gen_token(user["user_id"], phone)
    await db.login_sessions.update_one(
        {"token": data.token},
        {"$set": {
            "status": "verified",
            "auth_token": auth_token,
            "user": {"user_id": user["user_id"], "phone": phone,
                     "name": user.get("name", ""), "email": user.get("email", "")},
            "is_new_user": is_new,
        }}
    )
    return {"success": True, "message": "Login verified on this device"}


@router.get("/login-status/{token}")
async def login_status(token: str):
    """Desktop polls this. Returns pending | verified | expired (+ user when verified)."""
    from database import get_db
    db = get_db()

    sess = await db.login_sessions.find_one({"token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    if sess["status"] == "pending" and datetime.utcnow() > sess["expires_at"]:
        await db.login_sessions.update_one({"token": token}, {"$set": {"status": "expired"}})
        return {"status": "expired"}

    if sess["status"] == "verified":
        return {
            "status": "verified",
            "token": sess.get("auth_token"),
            "user": sess.get("user"),
            "is_new_user": sess.get("is_new_user", False),
        }
    return {"status": sess["status"]}
