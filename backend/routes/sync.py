"""Manual transfer to the RHU: status, transfer files and receipts."""
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from core.auth import AuthContext, require_admin
from core.storage import get_db
from core.sync_state import accept_receipt, bundle_file, cancel_bundle, create_bundle, list_bundles, set_passphrase
from core.sync_state import status as sync_status

router = APIRouter()


class SyncCounts(BaseModel):
    pending: int
    awaiting: int
    synced: int


class SyncStatus(BaseModel):
    station_id: str
    passphrase_set: bool
    records: dict[str, SyncCounts]
    last_acknowledged_at: str | None
    open_bundles: int


class SyncSettings(BaseModel):
    passphrase: str = Field(min_length=12, max_length=200)


class BundleSummary(BaseModel):
    id: str
    record_count: int
    created_at: str
    acknowledged_at: str | None
    created_by_name: str


@router.get("/sync/status", response_model=SyncStatus, operation_id="getSyncStatus")
def get_status(db: sqlite3.Connection = Depends(get_db)):
    return sync_status(db)


@router.put("/sync/settings", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)],
            operation_id="updateSyncSettings")
def update_settings(data: SyncSettings, db: sqlite3.Connection = Depends(get_db)):
    set_passphrase(db, data.passphrase)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sync/bundles", response_model=list[BundleSummary], operation_id="listSyncBundles")
def bundles(db: sqlite3.Connection = Depends(get_db)):
    return list_bundles(db)


@router.post("/sync/bundles", status_code=status.HTTP_201_CREATED, operation_id="createSyncBundle")
def new_bundle(auth: AuthContext = Depends(require_admin), db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return create_bundle(db, auth.user["id"])


@router.get("/sync/bundles/{bundle_id}", dependencies=[Depends(require_admin)], operation_id="getSyncBundle")
def get_bundle(bundle_id: str, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    bundle = bundle_file(db, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Transfer file not found")
    return bundle


@router.post("/sync/bundles/{bundle_id}/cancel", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(require_admin)], operation_id="cancelSyncBundle")
def cancel(bundle_id: str, db: sqlite3.Connection = Depends(get_db)):
    if cancel_bundle(db, bundle_id) is None:
        raise HTTPException(status_code=404, detail="Transfer file not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync/receipts", response_model=BundleSummary, dependencies=[Depends(require_admin)],
             operation_id="acceptSyncReceipt")
def receipts(receipt: dict[str, Any], db: sqlite3.Connection = Depends(get_db)):
    return accept_receipt(db, receipt)
