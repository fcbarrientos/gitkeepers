"""All paths and environment-driven settings live here"""
import os
import sys
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "YourAppName"  # TODO: rename once the product has a name

# Data lives in the OS user-data folder, not next to the code, so app updates
# and read-only install locations don't touch it. Override with APP_DATA_DIR.
DATA_DIR = Path(os.environ.get("APP_DATA_DIR") or user_data_dir(APP_NAME))
DB_PATH = DATA_DIR / "app.db"
MODELS_DIR = DATA_DIR / "models"

# Works both from source and when bundled with PyInstaller.
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
MIGRATIONS_DIR = _BASE / "migrations"

# Comma-separated origins the desktop UI calls from. Ask the frontend team for theirs.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,tauri://localhost,http://tauri.localhost",
).split(",") if o.strip()]

# If set, every request (except /health) must send header X-API-Token with this value.
# The desktop shell should generate a random one at launch and pass it in.
API_TOKEN = os.environ.get("API_TOKEN") or None


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
