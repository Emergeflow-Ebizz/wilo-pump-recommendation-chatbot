"""Vercel entrypoint.

@vercel/python looks for a variable named `app` in this file. The real
FastAPI app and all its routes live in app/main.py unprefixed (e.g.
/water_transfer/recommend); mounting it at /api here - rather than editing
its route decorators - is what makes vercel.json's "/api/(.*)" routing rule
line up, while local `uvicorn app.main:app` runs still hit the same routes
unprefixed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.main import app as pump_chatbot_app

app = FastAPI()
app.mount("/api", pump_chatbot_app)

# Local dev only: Vercel serves static/** itself via vercel.json and never
# hits this process for those paths, so mounting it here has no effect in
# prod - it only makes `uvicorn index:app` usable standalone for local
# frontend testing without a separate static file server.
_STATIC_DIR = Path(__file__).parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
