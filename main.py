import os
import secrets
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

# SQLite by default; set DATABASE_URL to use another database (e.g. PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./todos.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)

# Set SECRET_KEY in production. Without it a random key is generated at startup,
# which is safe but signs everyone out whenever the app restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
ALGORITHM = "HS256"
TOKEN_MINUTES = 60

hasher = PasswordHasher()
# Checked when a username doesn't exist, so unknown users cost the same time
# as known ones and login timing doesn't reveal which usernames are registered.
DUMMY_HASH = hasher.hash("not-a-real-password")

STATIC_DIR = Path(__file__).parent / "static"


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str]


class TodoRow(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(default=None)
    completed: Mapped[bool] = mapped_column(default=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="To-Do API", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    completed: bool | None = None


class Todo(TodoCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    completed: bool = False


def create_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)
    claims = {"sub": str(user_id), "exp": expires}
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: DbSession,
) -> UserRow:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        claims = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    user = db.get(UserRow, user_id)
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[UserRow, Depends(current_user)]


def get_or_404(db: Session, todo_id: int, user: UserRow) -> TodoRow:
    row = db.get(TodoRow, todo_id)
    # Someone else's todo gets the same 404 as a missing one
    if row is None or row.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Todo not found")
    return row


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, db: DbSession) -> UserOut:
    row = UserRow(
        username=payload.username.lower(),
        password_hash=hasher.hash(payload.password),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is taken.") from None
    db.refresh(row)
    return row


@app.post("/auth/login")
def login(payload: LoginRequest, db: DbSession) -> Token:
    user = db.scalar(
        select(UserRow).where(UserRow.username == payload.username.lower())
    )
    try:
        hasher.verify(user.password_hash if user else DUMMY_HASH, payload.password)
        valid = user is not None
    except VerifyMismatchError:
        valid = False
    if user is None or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_token(user.id))


@app.get("/todos")
def list_todos(
    db: DbSession, user: CurrentUser, completed: bool | None = None
) -> list[Todo]:
    query = select(TodoRow).where(TodoRow.owner_id == user.id).order_by(TodoRow.id)
    if completed is not None:
        query = query.where(TodoRow.completed == completed)
    return list(db.scalars(query))


@app.post("/todos", status_code=status.HTTP_201_CREATED)
def create_todo(payload: TodoCreate, db: DbSession, user: CurrentUser) -> Todo:
    row = TodoRow(**payload.model_dump(), owner_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.get("/todos/{todo_id}")
def read_todo(todo_id: int, db: DbSession, user: CurrentUser) -> Todo:
    return get_or_404(db, todo_id, user)


@app.patch("/todos/{todo_id}")
def update_todo(
    todo_id: int, payload: TodoUpdate, db: DbSession, user: CurrentUser
) -> Todo:
    row = get_or_404(db, todo_id, user)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int, db: DbSession, user: CurrentUser) -> None:
    row = get_or_404(db, todo_id, user)
    db.delete(row)
    db.commit()
