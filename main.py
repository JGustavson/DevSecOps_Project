import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, create_engine, select
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

STATIC_DIR = Path(__file__).parent / "static"


class Base(DeclarativeBase):
    pass


class TodoRow(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(default=None)
    completed: Mapped[bool] = mapped_column(default=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="To-Do API", lifespan=lifespan)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


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


def get_or_404(db: Session, todo_id: int) -> TodoRow:
    row = db.get(TodoRow, todo_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return row


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/todos")
def list_todos(db: DbSession, completed: bool | None = None) -> list[Todo]:
    query = select(TodoRow).order_by(TodoRow.id)
    if completed is not None:
        query = query.where(TodoRow.completed == completed)
    return list(db.scalars(query))


@app.post("/todos", status_code=status.HTTP_201_CREATED)
def create_todo(payload: TodoCreate, db: DbSession) -> Todo:
    row = TodoRow(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.get("/todos/{todo_id}")
def read_todo(todo_id: int, db: DbSession) -> Todo:
    return get_or_404(db, todo_id)


@app.patch("/todos/{todo_id}")
def update_todo(todo_id: int, payload: TodoUpdate, db: DbSession) -> Todo:
    row = get_or_404(db, todo_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int, db: DbSession) -> None:
    row = get_or_404(db, todo_id)
    db.delete(row)
    db.commit()
