"""Report summaries and AI-assisted drafts (reviewed and approved by a person)."""
import sqlite3
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from core import clock
from core.assist import get_assist_llm
from core.auth import AuthContext, current_user
from core.reports import create_ai_draft, create_manual_draft, list_drafts, summary, update_draft
from core.storage import get_db

router = APIRouter()
Period = Literal["week", "month"]


class DraftRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    period: Period
    day: date = Field(alias="date")


class ManualDraft(DraftRequest):
    text: str = Field(max_length=5000)


class DraftUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=5000)
    status: Literal["approved"] | None = None


class ReportDraft(BaseModel):
    id: str
    period: Period
    start_date: str
    end_date: str
    figures: dict[str, Any]
    text: str
    status: Literal["draft", "approved"]
    model: str | None
    created_by: str
    approved_by: str | None
    created_at: str
    updated_at: str


@router.get("/reports/summary", operation_id="getReportSummary")
def report_summary(period: Period = "week", day: date | None = Query(default=None, alias="date"),
                   db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return summary(db, period, day or clock.today())


@router.get("/reports/drafts", response_model=list[ReportDraft], operation_id="listReportDrafts")
def drafts(period: Period = "week", day: date | None = Query(default=None, alias="date"),
           db: sqlite3.Connection = Depends(get_db)):
    return list_drafts(db, period, day or clock.today())


@router.post("/reports/drafts", response_model=ReportDraft, status_code=status.HTTP_201_CREATED,
             operation_id="createAiReportDraft")
def ai_draft(data: DraftRequest, auth: AuthContext = Depends(current_user), db: sqlite3.Connection = Depends(get_db),
             llm=Depends(get_assist_llm)):
    return create_ai_draft(db, llm, data.period, data.day, auth.user["id"])


@router.post("/reports/drafts/manual", response_model=ReportDraft, status_code=status.HTTP_201_CREATED,
             operation_id="createManualReportDraft")
def manual_draft(data: ManualDraft, auth: AuthContext = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return create_manual_draft(db, data.period, data.day, data.text, auth.user["id"])


@router.patch("/reports/drafts/{draft_id}", response_model=ReportDraft, operation_id="updateReportDraft")
def edit_draft(draft_id: str, data: DraftUpdate, auth: AuthContext = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    draft = update_draft(db, draft_id, data.model_dump(exclude_unset=True), auth.user["id"])
    if draft is None:
        raise HTTPException(status_code=404, detail="Report draft not found")
    return draft
