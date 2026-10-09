"""Versioned HTTP endpoints for household and patient records."""
import sqlite3
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.records import (
    add_patient,
    create_household,
    get_household,
    get_patient,
    list_households,
    list_patients,
)
from core.storage import get_db

router = APIRouter()


class PatientCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    birth_date: date | None = None
    sex: Literal["female", "male", "intersex", "unknown"] | None = None
    relationship_to_head: str | None = Field(default=None, max_length=80)
    contact_number: str | None = Field(default=None, max_length=40)
    is_household_head: bool = False

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name must not be blank")
        return value


class HouseholdCreate(BaseModel):
    barangay: str = Field(min_length=1, max_length=120)
    sitio: str | None = Field(default=None, max_length=120)
    address_line: str | None = Field(default=None, max_length=240)
    contact_number: str | None = Field(default=None, max_length=40)
    members: list[PatientCreate] = Field(default_factory=list, max_length=200)

    @field_validator("barangay")
    @classmethod
    def normalize_barangay(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("barangay must not be blank")
        return value

    @model_validator(mode="after")
    def has_at_most_one_head(self):
        if sum(member.is_household_head for member in self.members) > 1:
            raise ValueError("A household can have at most one head")
        return self


class PatientRecord(PatientCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    created_at: str
    updated_at: str


class HouseholdDetail(BaseModel):
    id: str
    barangay: str
    sitio: str | None
    address_line: str | None
    contact_number: str | None
    created_at: str
    updated_at: str
    members: list[PatientRecord]


class HouseholdSummary(BaseModel):
    id: str
    barangay: str
    sitio: str | None
    address_line: str | None
    contact_number: str | None
    updated_at: str
    member_count: int
    head_name: str | None


class PatientSummary(PatientRecord):
    barangay: str
    sitio: str | None


class HouseholdPage(BaseModel):
    items: list[HouseholdSummary]
    total: int
    limit: int
    offset: int


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int
    limit: int
    offset: int


@router.get("/households", response_model=HouseholdPage, operation_id="listHouseholds")
def households(
    q: str | None = Query(default=None, max_length=120, description="Search household address or member name"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_households(db, q.strip() if q is not None else None, limit, offset)


@router.post(
    "/households",
    response_model=HouseholdDetail,
    status_code=status.HTTP_201_CREATED,
    operation_id="createHousehold",
)
def register_household(data: HouseholdCreate, db: sqlite3.Connection = Depends(get_db)):
    try:
        return create_household(db, data.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A household member conflicts with an existing record") from exc


@router.get(
    "/households/{household_id}",
    response_model=HouseholdDetail,
    operation_id="getHousehold",
)
def household_detail(household_id: str, db: sqlite3.Connection = Depends(get_db)):
    household = get_household(db, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return household


@router.post(
    "/households/{household_id}/members",
    response_model=PatientRecord,
    status_code=status.HTTP_201_CREATED,
    operation_id="addHouseholdMember",
)
def register_member(
    household_id: str,
    member: PatientCreate,
    db: sqlite3.Connection = Depends(get_db),
):
    try:
        patient = add_patient(db, household_id, member.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This household already has a head member") from exc
    if patient is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return patient


@router.get("/patients", response_model=PatientPage, operation_id="listPatients")
def patients(
    q: str | None = Query(default=None, max_length=120, description="Search patient name or contact number"),
    household_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_patients(
        db,
        q.strip() if q is not None else None,
        household_id,
        limit,
        offset,
    )


@router.get("/patients/{patient_id}", response_model=PatientSummary, operation_id="getPatient")
def patient_detail(patient_id: str, db: sqlite3.Connection = Depends(get_db)):
    patient = get_patient(db, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient
