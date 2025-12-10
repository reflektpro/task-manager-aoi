# tests/test_files.py
import io
import pytest
from app import app, init_db

@pytest.fixture(scope="module")
def client():
    with app.app_context():
        init_db()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def login(client, email, password):
    resp = client.post("/auth/login", json={
        "email": email,
        "password": password,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    return data["token"], data["user"]

def test_upload_file_ok(client):
    token, user = login(client, "admin@mail.ru", "123456")

    data = {
        "files": (io.BytesIO(b"hello world"), "test.txt")
    }
    resp = client.post(
        "/api/tasks/1/files",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        content_type="multipart/form-data",
    )

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["files"]) == 1
    f = data["files"][0]
    assert f["original_name"] == "test.txt"
    assert f["task_id"] == 1

def test_upload_file_forbidden_for_user(client):
    token, user = login(client, "ivan@mail.ru", "123456")

    data = {"files": (io.BytesIO(b"hello"), "user.txt")}
    resp = client.post(
        "/api/tasks/1/files",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 403

def test_upload_file_task_not_found(client):
    token, user = login(client, "admin@mail.ru", "123456")

    data = {"files": (io.BytesIO(b"hello"), "nofile.txt")}
    resp = client.post(
        "/api/tasks/999999/files",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404
