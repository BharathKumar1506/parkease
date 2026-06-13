from pydantic import BaseModel
from typing import Optional, List

# ── Booking ──────────────────────────────────────────────
class CreateBookingRequest(BaseModel):
    lot_id: int
    lot_name: str
    floor: str
    slot_label: str
    is_premium: bool = False
    user_name: str
    user_phone: str
    user_email: Optional[str] = ""
    vehicle_number: str
    vehicle_type: str
    vehicle_model: Optional[str] = ""
    entry_time: str
    exit_time: str
    hours: float
    total_amount: float
    promo_code: Optional[str] = ""
    discount: Optional[float] = 0
    payment_method: Optional[str] = "card"
    upi_txn_id: Optional[str] = ""         # NEW: from dummy UPI flow
    upi_ref: Optional[str] = ""            # NEW: bank reference from dummy UPI flow

# ── Lots ─────────────────────────────────────────────────
class CreateLotRequest(BaseModel):
    lot_id: int
    name: str
    address: str
    city: str
    price_per_hour: float
    premium_price_per_hour: float
    total_slots: int
    available_slots: int
    floors: List[str]
    amenities: Optional[List[str]] = []
    image_url: Optional[str] = ""
    rating: Optional[float] = 4.0
    distance: Optional[str] = ""

class UpdateLotRequest(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    price_per_hour: Optional[float] = None
    premium_price_per_hour: Optional[float] = None
    total_slots: Optional[int] = None
    available_slots: Optional[int] = None
    floors: Optional[List[str]] = None
    amenities: Optional[List[str]] = None
    image_url: Optional[str] = None
    rating: Optional[float] = None
    distance: Optional[str] = None

# ── Slots ─────────────────────────────────────────────────
class CreateSlotRequest(BaseModel):
    lot_id: int
    floor: str
    slot_label: str
    is_premium: bool = False

class CreateFloorSlotsRequest(BaseModel):
    lot_id: int
    floor: str
    normal_count: int
    premium_count: int

class UpdateSlotStatusRequest(BaseModel):
    lot_id: int
    floor: str
    slot_label: str
    status: str  # available | occupied | maintenance

# ── Admin ────────────────────────────────────────────────
class AdminLogin(BaseModel):
    username: str
    password: str
