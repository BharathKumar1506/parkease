from fastapi import APIRouter, HTTPException
from database import get_db
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])

class CreateReviewRequest(BaseModel):
    lot_id: int
    lot_name: str
    stars: int
    text: Optional[str] = ""
    user_name: Optional[str] = "Anonymous"
    booking_id: Optional[str] = ""

@router.post("/")
async def create_review(data: CreateReviewRequest):
    db = get_db()
    review = {
        "lot_id":     data.lot_id,
        "lot_name":   data.lot_name,
        "stars":      data.stars,
        "text":       data.text,
        "user_name":  data.user_name,
        "booking_id": data.booking_id,
        "created_at": datetime.utcnow()
    }
    await db.reviews.insert_one(review)

    # Update lot average rating
    pipeline = [
        {"$match": {"lot_id": data.lot_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$stars"}}}
    ]
    result = await db.reviews.aggregate(pipeline).to_list(1)
    if result:
        avg = round(result[0]["avg"], 1)
        await db.lots.update_one({"lot_id": data.lot_id}, {"$set": {"rating": avg}})

    return {"success": True, "message": "Review saved"}

@router.get("/{lot_id}")
async def get_reviews(lot_id: int):
    db = get_db()
    reviews = await db.reviews.find(
        {"lot_id": lot_id}, {"_id": 0}
    ).sort("created_at", -1).limit(20).to_list(20)
    for r in reviews:
        r["created_at"] = r["created_at"].isoformat()
    return {"success": True, "reviews": reviews}
