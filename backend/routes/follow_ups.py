"""Follow-up scheduling and tracking."""
import sqlite3
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.auth import AuthContext, current_user
from core.follow_ups import complete_follow_up, create_follow_up, list_follow_ups, update_follow_up
from core.storage import get_db

router = APIRouter()
State = Literal["overdue", "due", "upcoming", "completed", "cancelled"]


class FollowUp(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    barangay: str
    source_visit_id: str | None
    form_type: str | None
    due_date: str
    reason: str | None
    status: Literal["scheduled", "completed", "cancelled"]
    state: State
    completed_visit_id: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


class FollowUpPage(BaseModel):
    items: list[FollowUp]
    total: int
    limit: int
    offset: int


class FollowUpCreate(BaseModel):
    due_date: date
    reason: str | None = Field(default=None, max_length=500)
    form_type: str | None = Field(default=None, max_length=40)


class FollowUpUpdate(BaseModel):
    due_date: date | None = None
    reason: str | None = Field(default=None, max_length=500)
    status: Literal["cancelled"] | None = None


class FollowUpComplete(BaseModel):
    visit_id: str | None = None


def _found(follow_up: dict | None) -> dict:
    if follow_up is None:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return follow_up


@router.get("/follow-ups", response_model=FollowUpPage, operation_id="listFollowUps")
def follow_ups(
    state: State | None = None,
    patient_id: str | None = None,
    q: str | None = Query(default=None, max_length=120, description="Search patient name"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_follow_ups(db, state, patient_id, q.strip() if q else None, limit, offset)


@router.post("/patients/{patient_id}/follow-ups", response_model=FollowUp,
             status_code=status.HTTP_201_CREATED, operation_id="createFollowUp")
def schedule_follow_up(
    patient_id: str,
    data: FollowUpCreate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    follow_up = create_follow_up(db, patient_id, data.model_dump(), auth.user["id"])
    if follow_up is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return follow_up


@router.patch("/follow-ups/{follow_up_id}", response_model=FollowUp, operation_id="updateFollowUp")
def change_follow_up(follow_up_id: str, data: FollowUpUpdate, db: sqlite3.Connection = Depends(get_db)):
    return _found(update_follow_up(db, follow_up_id, data.model_dump(exclude_unset=True)))


@router.post("/follow-ups/{follow_up_id}/complete", response_model=FollowUp, operation_id="completeFollowUp")
def finish_follow_up(follow_up_id: str, data: FollowUpComplete, db: sqlite3.Connection = Depends(get_db)):
    return _found(complete_follow_up(db, follow_up_id, data.visit_id))
