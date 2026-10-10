"""Home dashboard summary."""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.dashboard import summary
from core.storage import get_db
from routes.forms import AIStatus

router = APIRouter()


class FollowUpCounts(BaseModel):
    overdue: int
    due: int
    upcoming: int


class Dashboard(BaseModel):
    follow_ups: FollowUpCounts
    visits_today: int
    drafts: int
    households: int
    patients: int
    referral_flags_open: int
    low_stock: int
    unsynced: int
    ai: AIStatus


@router.get("/dashboard", response_model=Dashboard, operation_id="getDashboard")
def dashboard(db: sqlite3.Connection = Depends(get_db)):
    return summary(db)
