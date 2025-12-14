# tests/test_files.py
import io
import pytest
from app import app
from database import init_db, save_task_file

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

def test_save_task_file():
    task_id = 1  # ID задачи
    original_name = "test_file.txt"
    stored_name = "stored_test_file.txt"
    content_type = "text/plain"
    size_bytes = 1024
    uploader_id = 1  # ID пользователя

    result = save_task_file(task_id, stored_name, original_name, content_type, size_bytes, uploader_id)
    assert result is not None
    assert result['original_name'] == original_name
    assert result['stored_name'] == stored_name
    assert result['content_type'] == content_type
    assert result['size_bytes'] == size_bytes
