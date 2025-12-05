# tests/debug_api.py
import os
import sys

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app


def print_response(resp, title=None):
    if title:
        print("=" * 20, title, "=" * 20)
    print("STATUS:", resp.status_code)
    try:
        print("JSON:", resp.get_json())
    except Exception:
        print("RAW DATA:", resp.data)
    print()


def main():
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Главная
        resp = client.get("/")
        print_response(resp, "GET /")

        # Пользователи
        resp = client.get("/api/users")
        print_response(resp, "GET /api/users")

        # Одна задача (если есть id=1)
        resp = client.get("/api/tasks/1")
        print_response(resp, "GET /api/tasks/1")

        # Создание задачи
        payload = {
            "title": "Задача из debug_api",
            "author_id": 1
        }
        resp = client.post("/api/tasks", json=payload)
        print_response(resp, "POST /api/tasks")
        data = resp.get_json()
        task_id = data["task"]["id"]

        # Обновление задачи
        resp = client.put(f"/api/tasks/{task_id}", json={"status": "в процессе"})
        print_response(resp, "PUT /api/tasks/<id>")

        # Удаление задачи
        resp = client.delete(f"/api/tasks/{task_id}")
        print_response(resp, "DELETE /api/tasks/<id>")

        # Логин
        resp = client.post("/auth/login", json={
            "email": "admin@mail.ru",
            "password": "123456"
        })
        print_response(resp, "POST /auth/login")


if __name__ == "__main__":
    main()
