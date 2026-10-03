from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="To-Do API")

STATIC_DIR = Path(__file__).parent / "static"


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    completed: bool | None = None


class Todo(TodoCreate):
    id: int
    completed: bool = False


# In-memory store: resets whenever the server restarts
todos: dict[int, Todo] = {}


def get_or_404(todo_id: int) -> Todo:
    todo = todos.get(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/todos")
def list_todos(completed: bool | None = None) -> list[Todo]:
    items = list(todos.values())
    if completed is not None:
        items = [t for t in items if t.completed == completed]
    return items


@app.post("/todos", status_code=status.HTTP_201_CREATED)
def create_todo(payload: TodoCreate) -> Todo:
    todo_id = max(todos, default=0) + 1
    todo = Todo(id=todo_id, **payload.model_dump())
    todos[todo_id] = todo
    return todo


@app.get("/todos/{todo_id}")
def read_todo(todo_id: int) -> Todo:
    return get_or_404(todo_id)


@app.patch("/todos/{todo_id}")
def update_todo(todo_id: int, payload: TodoUpdate) -> Todo:
    todo = get_or_404(todo_id)
    updated = todo.model_copy(update=payload.model_dump(exclude_none=True))
    todos[todo_id] = updated
    return updated


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int) -> None:
    get_or_404(todo_id)
    del todos[todo_id]
