"""Versioned HTTP endpoints for signup, login, and the signed-in user's own profile."""
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator

from core.auth import AuthContext, change_password, current_user, login, logout, signup, update_profile
from core.storage import get_db

router = APIRouter()

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _clean_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _EMAIL.fullmatch(value):
        raise ValueError("Invalid email address")
    return value


def _clean_name(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("full_name must not be blank")
    return value


class User(BaseModel):
    id: str
    username: str
    email: str | None
    full_name: str
    role: Literal["admin", "volunteer"]
    status: Literal["pending", "active", "disabled"]
    created_at: str
    updated_at: str


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _clean_email(value)


@router.post(
    "/auth/signup",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
    operation_id="signup",
)
def signup_endpoint(data: SignupRequest, db: sqlite3.Connection = Depends(get_db)):
    return signup(db, data.model_dump())


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=254, description="Username or email")
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    user: User


@router.post("/auth/login", response_model=LoginResponse, operation_id="login")
def login_endpoint(data: LoginRequest, db: sqlite3.Connection = Depends(get_db)):
    return login(db, data.login.strip(), data.password)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout")
def logout_endpoint(
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    logout(db, auth.token_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=User, operation_id="getCurrentUser")
def me(auth: AuthContext = Depends(current_user)):
    return auth.user


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)

    # Validators only run on fields the client actually sent, so omitted fields stay unchanged.
    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        return _clean_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _clean_email(value)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.patch("/me", response_model=User, operation_id="updateMyProfile")
def update_me(
    data: ProfileUpdate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    return update_profile(db, auth.user["id"], data.model_dump(exclude_unset=True))


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, operation_id="changeMyPassword")
def change_my_password(
    data: PasswordChange,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    change_password(db, auth, data.current_password, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
