from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import ALGORITHM, SECRET_KEY, Base, app, get_db

client = TestClient(app)
PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def database():
    """Give every test its own empty in-memory database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    engine.dispose()


def sign_up(username):
    """Register a user and return auth headers for them."""
    credentials = {"username": username, "password": PASSWORD}
    assert client.post("/auth/register", json=credentials).status_code == 201
    token = client.post("/auth/login", json=credentials).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice():
    return sign_up("alice")


def create(headers, title="Buy milk"):
    return client.post("/todos", json={"title": title}, headers=headers)


def test_index_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_create_todo(alice):
    response = create(alice)
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "title": "Buy milk",
        "description": None,
        "completed": False,
    }


def test_create_todo_rejects_empty_title(alice):
    response = client.post("/todos", json={"title": ""}, headers=alice)
    assert response.status_code == 422


def test_list_todos_with_filter(alice):
    create(alice, "one")
    create(alice, "two")
    client.patch("/todos/2", json={"completed": True}, headers=alice)

    assert len(client.get("/todos", headers=alice).json()) == 2
    done = client.get("/todos", params={"completed": True}, headers=alice).json()
    assert [t["title"] for t in done] == ["two"]


def test_read_todo(alice):
    create(alice)
    response = client.get("/todos/1", headers=alice)
    assert response.status_code == 200
    assert response.json()["title"] == "Buy milk"


def test_update_todo(alice):
    create(alice)
    response = client.patch("/todos/1", json={"completed": True}, headers=alice)
    assert response.status_code == 200
    assert response.json()["completed"] is True
    assert response.json()["title"] == "Buy milk"


def test_delete_todo(alice):
    create(alice)
    assert client.delete("/todos/1", headers=alice).status_code == 204
    assert client.get("/todos/1", headers=alice).status_code == 404


def test_missing_todo_returns_404(alice):
    assert client.get("/todos/999", headers=alice).status_code == 404
    patch = client.patch("/todos/999", json={"completed": True}, headers=alice)
    assert patch.status_code == 404
    assert client.delete("/todos/999", headers=alice).status_code == 404


def test_todos_require_authentication():
    assert client.get("/todos").status_code == 401
    assert client.post("/todos", json={"title": "x"}).status_code == 401
    assert client.get("/todos/1").status_code == 401
    assert client.patch("/todos/1", json={"completed": True}).status_code == 401
    assert client.delete("/todos/1").status_code == 401


def test_invalid_token_is_rejected():
    headers = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/todos", headers=headers).status_code == 401


def test_expired_token_is_rejected(alice):
    claims = {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
    token = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/todos", headers=headers).status_code == 401


def test_token_signed_with_another_key_is_rejected(alice):
    claims = {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    token = jwt.encode(
        claims, "some-other-secret-key-of-32-bytes!!", algorithm=ALGORITHM
    )
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/todos", headers=headers).status_code == 401


def test_register_rejects_duplicate_username(alice):
    credentials = {"username": "ALICE", "password": PASSWORD}
    response = client.post("/auth/register", json=credentials)
    assert response.status_code == 409


def test_register_rejects_weak_password():
    credentials = {"username": "carol", "password": "short"}
    assert client.post("/auth/register", json=credentials).status_code == 422


def test_register_rejects_bad_username():
    credentials = {"username": "no spaces!", "password": PASSWORD}
    assert client.post("/auth/register", json=credentials).status_code == 422


def test_login_failures_look_identical(alice):
    wrong_password = client.post(
        "/auth/login", json={"username": "alice", "password": "wrong-password"}
    )
    unknown_user = client.post(
        "/auth/login", json={"username": "nobody", "password": PASSWORD}
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_users_cannot_see_each_others_todos(alice):
    bob = sign_up("bob")
    create(alice)

    assert client.get("/todos", headers=bob).json() == []
    assert client.get("/todos/1", headers=bob).status_code == 404
    patch = client.patch("/todos/1", json={"completed": True}, headers=bob)
    assert patch.status_code == 404
    assert client.delete("/todos/1", headers=bob).status_code == 404
    assert len(client.get("/todos", headers=alice).json()) == 1
