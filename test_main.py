import pytest
from fastapi.testclient import TestClient

from main import app, todos

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_todos():
    todos.clear()
    yield
    todos.clear()


def create(title="Buy milk"):
    return client.post("/todos", json={"title": title})


def test_create_todo():
    response = create()
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "title": "Buy milk",
        "description": None,
        "completed": False,
    }


def test_create_todo_rejects_empty_title():
    response = client.post("/todos", json={"title": ""})
    assert response.status_code == 422


def test_list_todos_with_filter():
    create("one")
    create("two")
    client.patch("/todos/2", json={"completed": True})

    assert len(client.get("/todos").json()) == 2
    done = client.get("/todos", params={"completed": True}).json()
    assert [t["title"] for t in done] == ["two"]


def test_read_todo():
    create()
    response = client.get("/todos/1")
    assert response.status_code == 200
    assert response.json()["title"] == "Buy milk"


def test_update_todo():
    create()
    response = client.patch("/todos/1", json={"completed": True})
    assert response.status_code == 200
    assert response.json()["completed"] is True
    assert response.json()["title"] == "Buy milk"


def test_delete_todo():
    create()
    assert client.delete("/todos/1").status_code == 204
    assert client.get("/todos/1").status_code == 404


def test_missing_todo_returns_404():
    assert client.get("/todos/999").status_code == 404
    assert client.patch("/todos/999", json={"completed": True}).status_code == 404
    assert client.delete("/todos/999").status_code == 404


def test_index_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
