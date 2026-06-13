from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from datetime import datetime
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

from database import connect_db, disconnect_db
from routes import lots, slots, bookings, admin, reviews, payments, websocket, auth

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield
    await disconnect_db()

app = FastAPI(
    title="ParkEase API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(lots.router)
app.include_router(slots.router)
app.include_router(bookings.router)
app.include_router(reviews.router)
app.include_router(admin.router)
app.include_router(payments.router)
app.include_router(websocket.router)   # real-time slots
app.include_router(auth.router)        # OTP login

from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    # Send visitors straight to the app
    return RedirectResponse(url="/frontend/ParkEase.html")

@app.get("/api")
async def api_root():
    return {"app": "ParkEase API", "status": "running", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}

# ── Serve frontend static files from /frontend on the SAME port (8000) ───────
# This means the mobile only needs to reach one port (8000) for BOTH
# the HTML pages AND the API — no separate Live Server port needed.
#
# Access your app at:  http://192.168.29.120:8000/frontend/ParkEase.html
# The API is at:       http://192.168.29.120:8000/api/...
#
_frontend_dir = pathlib.Path(__file__).parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    # Render/Railway provide PORT; default 8000 for local dev.
    port = int(os.getenv("PORT", "8000"))
    # reload only locally (RELOAD=1); off in production
    reload_flag = os.getenv("RELOAD", "1") == "1" and os.getenv("PORT") is None
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload_flag)
