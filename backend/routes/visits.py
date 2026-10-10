"""Checkup visits and AI field suggestions for a patient."""
import sqlite3
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.assist import get_assist_llm, suggest
from core.auth import AuthContext, current_user
from core.errors import ApiError
from core.forms import get_form
from core.storage import get_db
from core.visits import create_visit, get_visit, list_recent_visits, list_visits, update_visit

router = APIRouter()


def _form_or_422(form_type: str) -> dict:
    form = get_form(form_type)
    if form is None:
        raise ApiError(422, ["form_type: unknown form"])
    return form


class SuggestionRequest(BaseModel):
    form_type: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=5000)


class Suggestion(BaseModel):
    suggestion_id: str
    form_type: str
    values: dict[str, Any]
    missing: list[str]
    problems: list[str]


@router.post("/patients/{patient_id}/suggestions", response_model=Suggestion, operation_id="suggestVisitValues")
def suggest_values(
    patient_id: str,
    data: SuggestionRequest,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
    llm=Depends(get_assist_llm),
):
    result = suggest(db, llm, patient_id, _form_or_422(data.form_type), data.note, auth.user["id"])
    if result is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return result


class FollowUpPlan(BaseModel):
    due_date: date
    reason: str | None = Field(default=None, max_length=500)


class VisitCreate(BaseModel):
    form_type: str = Field(min_length=1, max_length=40)
    visit_date: date
    values: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=5000)
    status: Literal["draft", "final"] = "draft"
    suggestion_id: str | None = None
    ai_accepted_fields: list[str] = Field(default_factory=list, max_length=100)
    follow_up: FollowUpPlan | None = None
    completes_follow_up_id: str | None = None


class VisitUpdate(BaseModel):
    visit_date: date | None = None
    values: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=5000)
    status: Literal["draft", "final"] | None = None
    suggestion_id: str | None = None
    ai_accepted_fields: list[str] | None = Field(default=None, max_length=100)
    follow_up: FollowUpPlan | None = None
    completes_follow_up_id: str | None = None


class Visit(BaseModel):
    id: str
    patient_id: str
    form_type: str
    visit_date: str
    status: Literal["draft", "final"]
    values: dict[str, Any]
    sources: dict[str, Literal["manual", "ai_accepted", "ai_edited"]]
    note: str | None
    suggestion_id: str | None
    recorded_by: str
    created_at: str
    updated_at: str
    finalized_at: str | None
    follow_up_created: dict[str, Any] | None = None


class VisitPage(BaseModel):
    items: list[Visit]
    total: int
    limit: int
    offset: int


class VisitSummary(Visit):
    patient_name: str


class VisitSummaryPage(BaseModel):
    items: list[VisitSummary]
    total: int
    limit: int
    offset: int


@router.get("/visits", response_model=VisitSummaryPage, operation_id="listVisits")
def visits(
    visit_date: date | None = Query(default=None, alias="date"),
    status_filter: Literal["draft", "final"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_recent_visits(db, visit_date, status_filter, limit, offset)


@router.post("/patients/{patient_id}/visits", response_model=Visit,
             status_code=status.HTTP_201_CREATED, operation_id="createVisit")
def record_visit(
    patient_id: str,
    data: VisitCreate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    visit = create_visit(db, patient_id, data.model_dump(), auth.user["id"])
    if visit is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return visit


@router.get("/patients/{patient_id}/visits", response_model=VisitPage, operation_id="listPatientVisits")
def patient_visits(
    patient_id: str,
    form_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    page = list_visits(db, patient_id, form_type, limit, offset)
    if page is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return page


@router.get("/visits/{visit_id}", response_model=Visit, operation_id="getVisit")
def visit_detail(visit_id: str, db: sqlite3.Connection = Depends(get_db)):
    visit = get_visit(db, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit


@router.patch("/visits/{visit_id}", response_model=Visit, operation_id="updateVisit")
def edit_visit(
    visit_id: str,
    data: VisitUpdate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    visit = update_visit(db, visit_id, data.model_dump(exclude_unset=True), auth.user["id"])
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit
