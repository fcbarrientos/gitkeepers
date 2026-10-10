"""Admin-only endpoints for approving, disabling, and managing user accounts."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from core.auth import AuthError, get_user, list_users, require_admin, reset_password, update_user
from core.storage import get_db
from routes.auth import User

router = APIRouter(dependencies=[Depends(require_admin)])


class UserPage(BaseModel):
    items: list[User]
    total: int
    limit: int
    offset: int


class UserUpdate(BaseModel):
    status: Literal["active", "disabled"] | None = None
    role: Literal["admin", "volunteer"] | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/users", response_model=UserPage, operation_id="listUsers")
def users(
    status_filter: Literal["pending", "active", "disabled"] | None = Query(default=None, alias="status"),
    role: Literal["admin", "volunteer"] | None = None,
    q: str | None = Query(default=None, max_length=120, description="Search username, name, or email"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_users(db, status_filter, role, q.strip() if q else None, limit, offset)


@router.get("/users/{user_id}", response_model=User, operation_id="getUser")
def user_detail(user_id: str, db: sqlite3.Connection = Depends(get_db)):
    user = get_user(db, user_id)
    if user is None:
        raise AuthError(404, "User not found")
    return user


@router.patch("/users/{user_id}", response_model=User, operation_id="updateUser")
def change_user(user_id: str, data: UserUpdate, db: sqlite3.Connection = Depends(get_db)):
    return update_user(db, user_id, data.model_dump(exclude_unset=True))


@router.post(
    "/users/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="resetUserPassword",
)
def reset_user_password(user_id: str, data: PasswordReset, db: sqlite3.Connection = Depends(get_db)):
    reset_password(db, user_id, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
