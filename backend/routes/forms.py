"""Form definitions and AI availability, so the frontend can render forms from data."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.assist import ai_status
from core.forms import get_form, list_forms

router = APIRouter()


class FormField(BaseModel):
    name: str
    type: Literal["integer", "number", "boolean", "choice", "choices"]
    label: dict[str, str]
    required: bool = False
    ai: bool = False
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None


class FormDefinition(BaseModel):
    form_type: str
    title: dict[str, str]
    verification: str
    default_follow_up_days: int
    fields: list[FormField]


class AIStatus(BaseModel):
    available: bool
    model: str | None


@router.get("/forms", response_model=list[FormDefinition], operation_id="listForms")
def forms():
    return list_forms()


@router.get("/forms/{form_type}", response_model=FormDefinition, operation_id="getForm")
def form_detail(form_type: str):
    form = get_form(form_type)
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")
    return form


@router.get("/ai/status", response_model=AIStatus, operation_id="getAIStatus")
def status():
    return ai_status()
