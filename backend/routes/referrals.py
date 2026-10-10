"""Referral rules, flags raised by them, and referral slips."""
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from core.auth import AuthContext, current_user
from core.referrals import create_referral, dismiss_flag, get_flag, get_referral, list_flags, list_referrals, load_rules
from core.storage import get_db

router = APIRouter()
Urgency = Literal["urgent", "routine"]


class ReferralRule(BaseModel):
    id: str
    urgency: Urgency
    reason: dict[str, str]
    when: dict[str, Any]


class RuleSet(BaseModel):
    form_type: str
    verification: str
    rules: list[ReferralRule]


class ReferralFlag(BaseModel):
    id: str
    visit_id: str
    patient_id: str
    patient_name: str
    rule_id: str
    reason_en: str
    reason_fil: str
    urgency: Urgency
    status: Literal["open", "referred", "dismissed"]
    dismiss_note: str | None
    created_at: str
    form_type: str
    visit_date: str


class FlagDismiss(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ReferralCreate(BaseModel):
    patient_id: str = Field(min_length=1, max_length=64)
    flag_id: str | None = Field(default=None, max_length=64)
    facility: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
    urgency: Urgency = "urgent"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("facility", "reason")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ReferralVisit(BaseModel):
    id: str
    form_type: str
    visit_date: str
    values: dict[str, Any]


class Referral(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    birth_date: str | None
    sex: str | None
    barangay: str
    sitio: str | None
    flag_id: str | None
    facility: str
    reason: str
    urgency: Urgency
    notes: str | None
    status: Literal["issued", "sent"]
    created_by: str
    created_by_name: str
    created_at: str
    updated_at: str
    visit: ReferralVisit | None


class ReferralPage(BaseModel):
    items: list[Referral]
    total: int
    limit: int
    offset: int


@router.get("/referral-rules", response_model=list[RuleSet], operation_id="listReferralRules")
def referral_rules():
    return list(load_rules().values())


@router.get("/referral-flags", response_model=list[ReferralFlag], operation_id="listReferralFlags")
def flags(
    status_filter: Literal["open", "referred", "dismissed"] | None = Query(default=None, alias="status"),
    patient_id: str | None = None,
    visit_id: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
):
    return list_flags(db, status_filter, patient_id, visit_id)


@router.get("/referral-flags/{flag_id}", response_model=ReferralFlag, operation_id="getReferralFlag")
def flag_detail(flag_id: str, db: sqlite3.Connection = Depends(get_db)):
    flag = get_flag(db, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="Referral flag not found")
    return flag


@router.post("/referral-flags/{flag_id}/dismiss", response_model=ReferralFlag, operation_id="dismissReferralFlag")
def dismiss(flag_id: str, data: FlagDismiss, db: sqlite3.Connection = Depends(get_db)):
    flag = dismiss_flag(db, flag_id, data.note)
    if flag is None:
        raise HTTPException(status_code=404, detail="Referral flag not found")
    return flag


@router.post("/referrals", response_model=Referral, status_code=status.HTTP_201_CREATED, operation_id="createReferral")
def new_referral(data: ReferralCreate, auth: AuthContext = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    referral = create_referral(db, data.model_dump(), auth.user["id"])
    if referral is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return referral


@router.get("/referrals", response_model=ReferralPage, operation_id="listReferrals")
def referrals(
    status_filter: Literal["issued", "sent"] | None = Query(default=None, alias="status"),
    patient_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_referrals(db, status_filter, patient_id, limit, offset)


@router.get("/referrals/{referral_id}", response_model=Referral, operation_id="getReferral")
def referral_detail(referral_id: str, db: sqlite3.Connection = Depends(get_db)):
    referral = get_referral(db, referral_id)
    if referral is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    return referral
