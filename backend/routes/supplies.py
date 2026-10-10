"""Medicine and supply inventory."""
import sqlite3
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from core.auth import AuthContext, current_user
from core.storage import get_db
from core.supplies import create_item, get_item, list_items, list_movements, record_movement, request_list, update_item

router = APIRouter()


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class SupplyItem(BaseModel):
    id: str
    name: str
    unit: str
    low_stock_threshold: int
    target_level: int
    active: bool
    on_hand: int
    low: bool
    created_at: str
    updated_at: str


class RequestItem(SupplyItem):
    request_quantity: int


class SupplyItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    low_stock_threshold: int = Field(ge=0, le=1_000_000)
    target_level: int = Field(ge=0, le=1_000_000)

    @field_validator("name", "unit")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        return _strip(value)


class SupplyItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=1_000_000)
    target_level: int | None = Field(default=None, ge=0, le=1_000_000)
    active: bool | None = None

    @field_validator("name", "unit")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        return _strip(value)


class MovementCreate(BaseModel):
    kind: Literal["received", "distributed", "adjusted"]
    quantity: int = Field(ge=-1_000_000, le=1_000_000)
    movement_date: date
    note: str | None = Field(default=None, max_length=500)


class Movement(BaseModel):
    id: str
    item_id: str
    kind: Literal["received", "distributed", "adjusted"]
    quantity: int
    movement_date: str
    note: str | None
    recorded_by: str
    recorded_by_name: str
    created_at: str


class MovementPage(BaseModel):
    items: list[Movement]
    total: int
    limit: int
    offset: int


def _found(item):
    if item is None:
        raise HTTPException(status_code=404, detail="Supply item not found")
    return item


@router.get("/supplies", response_model=list[SupplyItem], operation_id="listSupplies")
def supplies(include_inactive: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return list_items(db, include_inactive)


@router.post("/supplies", response_model=SupplyItem, status_code=status.HTTP_201_CREATED, operation_id="createSupply")
def new_supply(data: SupplyItemCreate, db: sqlite3.Connection = Depends(get_db)):
    return create_item(db, data.model_dump())


@router.get("/supplies/request-list", response_model=list[RequestItem], operation_id="supplyRequestList")
def supply_request_list(db: sqlite3.Connection = Depends(get_db)):
    return request_list(db)


@router.get("/supplies/{item_id}", response_model=SupplyItem, operation_id="getSupply")
def supply_detail(item_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _found(get_item(db, item_id))


@router.patch("/supplies/{item_id}", response_model=SupplyItem, operation_id="updateSupply")
def change_supply(item_id: str, data: SupplyItemUpdate, db: sqlite3.Connection = Depends(get_db)):
    return _found(update_item(db, item_id, data.model_dump(exclude_unset=True)))


@router.get("/supplies/{item_id}/movements", response_model=MovementPage, operation_id="listSupplyMovements")
def movements(item_id: str, limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
              db: sqlite3.Connection = Depends(get_db)):
    return _found(list_movements(db, item_id, limit, offset))


@router.post("/supplies/{item_id}/movements", response_model=Movement, status_code=status.HTTP_201_CREATED,
             operation_id="recordSupplyMovement")
def new_movement(item_id: str, data: MovementCreate, auth: AuthContext = Depends(current_user),
                 db: sqlite3.Connection = Depends(get_db)):
    return _found(record_movement(db, item_id, data.model_dump(), auth.user["id"]))
