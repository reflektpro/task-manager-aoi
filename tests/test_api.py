# tests/test_api.py
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def auth_token(client):
    resp = client.post("/auth/login", json={
        "email": "admin@mail.ru",
        "password": "123456"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    return data["token"]


# ===== БАЗОВЫЕ ТЕСТЫ =====

def test_home(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["project"] == "Task Manager API"
    assert "endpoints" in data


def test_get_users(client):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert isinstance(data["users"], list)
    # хотя бы один пользователь из test_data
    assert data["count"] >= 1


def test_get_user_by_id(client):
    # предполагаем, что пользователь с id=1 есть из add_test_data()
    resp = client.get("/api/users/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["user"]["id"] == 1


# ===== ЗАДАЧИ =====

def test_get_tasks(client):
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert isinstance(data["tasks"], list)


def test_create_task_success(client):
    # создаём новую задачу
    payload = {
        "title": "Тестовая задача из теста",
        "description": "Описание из теста",
        "author_id": 1,          # из test_data
        "priority": "высокий",
        "status": "к выполнению",
        "due_date": "2025-12-31"
    }
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    assert "task" in data
    task = data["task"]
    assert task["title"] == payload["title"]
    assert task["author_id"] == payload["author_id"]



def test_create_task_validation_error(client):
    # отправляем кривой статус
    payload = {
        "title": "Задача с неправильным статусом",
        "author_id": 1,
        "status": "какой-то левый статус"
    }
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Ошибки валидации"
    assert any("Недопустимый статус" in msg for msg in data["details"])


def test_task_lifecycle(client):
    """
    Полный цикл: создать → получить → обновить → удалить
    """
    # 1. Создаём задачу
    payload = {
        "title": "Жизненный цикл задачи",
        "author_id": 1,
    }
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 201
    task = resp.get_json()["task"]
    task_id = task["id"]

    # 2. Получаем по ID
    resp = client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["task"]["id"] == task_id

    # 3. Обновляем
    update_payload = {
        "title": "Обновлённый заголовок",
        "status": "в процессе",
        "priority": "средний",
    }
    resp = client.put(f"/api/tasks/{task_id}", json=update_payload)
    assert resp.status_code == 200
    updated = resp.get_json()["task"]
    assert updated["title"] == "Обновлённый заголовок"
    assert updated["status"] == "в процессе"
    assert updated["priority"] == "средний"

    # 4. Удаляем
    resp = client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    # 5. Проверяем, что больше не существует
    resp = client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 404


# ===== КОММЕНТАРИИ =====

def test_get_comments_for_existing_task(client):
    # В тестовых данных есть задача с id=1
    resp = client.get("/api/tasks/1/comments")
    assert resp.status_code in (200, 404)  # если вдруг задачу 1 удалили тестами
    if resp.status_code == 200:
        data = resp.get_json()
        assert data["success"] is True
        assert data["task_id"] == 1
        assert isinstance(data["comments"], list)


def test_add_and_delete_comment(client):
    # 1. Убедимся, что задача 1 существует (если нет — скипаем тест)
    resp_task = client.get("/api/tasks/1")
    if resp_task.status_code != 200:
        pytest.skip("Задача #1 отсутствует, пропускаем тест комментариев")

    # 2. Добавляем комментарий
    payload = {
        "text": "Комментарий из теста",
        "author_id": 1
    }
    resp = client.post("/api/tasks/1/comments", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    comment_id = data["comment"]["id"]

    # 3. Удаляем комментарий
    resp = client.delete(f"/api/comments/{comment_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


# ===== АУТЕНТИФИКАЦИЯ / МЕТОДЫ ДЛЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ =====

def test_login_success(client):
    payload = {
        "email": "admin@mail.ru",
        "password": "123456"
    }
    resp = client.post("/auth/login", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "token" in data


def test_login_fail(client):
    payload = {
        "email": "admin@mail.ru",
        "password": "wrong"
    }
    resp = client.post("/auth/login", json=payload)
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["success"] is False


def test_get_me(client, auth_token):
    resp = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["user"]["email"] == "admin@mail.ru"


def test_update_me(client, auth_token):
    payload = {"username": "Новый Админ"}
    resp = client.put(
        "/users/me",
        json=payload,
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["updated"]["username"] == "Новый Админ"





