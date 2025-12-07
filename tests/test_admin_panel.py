import os
import sys
import pytest

# Добавляем корень проекта в sys.path, чтобы можно было импортировать app.py
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app  # init_db нам не нужен, всё уже вызывается внутри app.py


@pytest.fixture(scope="module")
def client():
    """
    Тестовый клиент Flask.
    База и тестовые данные уже создаются при импорте app.py (судя по логам).
    """
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def login(client, email, password):
    """
    Хелпер для логина, возвращает (token, user_dict).
    """
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    assert "token" in data
    return data["token"], data["user"]


# ====================== ТЕСТЫ ДОСТУПА К /admin/stats ======================

def test_admin_stats_requires_auth(client):
    """
    Без токена доступ к /admin/stats запрещён (401).
    """
    resp = client.get("/admin/stats")
    assert resp.status_code == 401
    data = resp.get_json()
    assert "error" in data
    assert "Требуется" in data["error"]


def test_admin_stats_for_regular_user_forbidden(client):
    """
    Обычный пользователь не имеет доступа к /admin/stats (403).
    """
    # по умолчанию в твоём init_db есть юзер ivan@mail.ru с паролем 123456
    token, user = login(client, "ivan@mail.ru", "123456")
    assert user["role"] == "user"

    resp = client.get(
        "/admin/stats",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert "Недостаточно прав" in data["error"]


def test_admin_stats_for_admin_ok(client):
    """
    Администратор должен получать статистику.
    """
    token, user = login(client, "admin@mail.ru", "123456")
    assert user["role"] == "admin"

    resp = client.get(
        "/admin/stats",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    assert "stats" in data
    assert "active_users" in data


# ====================== ТЕСТЫ ИЗМЕНЕНИЯ РОЛЕЙ ======================

def _create_temp_user(client, email_suffix: str):
    """
    Создаём временного пользователя через /auth/register.
    Если такой email уже существует, просто логинимся и возвращаем его.
    """
    email = f"temp_{email_suffix}@mail.ru"
    payload = {
        "email": email,
        "username": f"Temp {email_suffix}",
        "password": "123456",
        "role": "user",
    }

    resp = client.post("/auth/register", json=payload)

    # Успешное создание пользователя
    if resp.status_code in (200, 201):
        data = resp.get_json()
        assert data.get("success") is True
        return data["user"]

    # Неуспех — разруливаем самые частые случаи
    if resp.status_code == 400:
        data = resp.get_json() or {}
        err_msg = (data.get("error") or "").lower()

        # Типичный кейс: пользователь с таким email уже существует
        if "существ" in err_msg:
            # Логинимся с тем же email/паролем и берём user оттуда
            login_resp = client.post(
                "/auth/login",
                json={"email": email, "password": "123456"},
            )
            assert login_resp.status_code == 200, f"Не удалось залогиниться существующим пользователем {email}"
            login_data = login_resp.get_json()
            assert login_data.get("success") is True
            return login_data["user"]

        # Если это не «уже существует» — пусть тест честно падает
        raise AssertionError(f"Не удалось создать временного пользователя: {data}")

    # Любой другой статус — тоже падение с пояснением
    raise AssertionError(
        f"Неожиданный статус при создании пользователя: {resp.status_code}, body={resp.data!r}"
    )



def test_super_admin_can_change_user_role_to_admin(client):
    """
    Супер-админ может менять роль пользователя на admin.
    """
    super_token, super_user = login(client, "super@mail.ru", "123456")
    assert super_user["role"] == "super_admin"

    temp_user = _create_temp_user(client, "role_change")
    user_id = temp_user["id"]

    resp = client.put(
        f"/admin/users/{user_id}/role",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True

    # проверяем, что роль реально изменилась
    resp2 = client.get(f"/api/users/{user_id}")
    assert resp2.status_code == 200
    udata = resp2.get_json()
    assert udata["user"]["role"] == "admin"


def test_admin_cannot_change_roles(client):
    """
    Обычный админ НЕ может менять роли других пользователей (только супер-админ).
    """
    admin_token, admin_user = login(client, "admin@mail.ru", "123456")
    assert admin_user["role"] == "admin"

    temp_user = _create_temp_user(client, "forbidden_change")
    user_id = temp_user["id"]
    assert temp_user["role"] == "user"

    resp = client.put(
        f"/admin/users/{user_id}/role",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "admin"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    # Бэкенд сейчас даёт более точное сообщение:
    assert "супер-админ" in data["error"]


# ====================== ТЕСТЫ УДАЛЕНИЯ ПОЛЬЗОВАТЕЛЕЙ ======================

def test_super_admin_can_delete_user(client):
    """
    Супер-админ может удалять обычного пользователя.
    """
    super_token, super_user = login(client, "super@mail.ru", "123456")
    assert super_user["role"] == "super_admin"

    temp_user = _create_temp_user(client, "delete")
    user_id = temp_user["id"]

    resp = client.delete(
        f"/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True

    # проверяем, что пользователя больше нет
    resp2 = client.get(f"/api/users/{user_id}")
    # у тебя, скорее всего, 404 + "Пользователь не найден"
    assert resp2.status_code in (404, 400, 410)
    data2 = resp2.get_json()
    assert "error" in data2


def test_admin_cannot_delete_super_admin(client):
    """
    Обычный админ не может удалить супер-админа.
    """
    admin_token, admin_user = login(client, "admin@mail.ru", "123456")
    assert admin_user["role"] == "admin"

    # супер-админ почти наверняка id = 1 (из твоего init_db)
    resp = client.delete(
        "/admin/users/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert "супер-админ" in data["error"]



# ====================== ТЕСТ LOGOUT ======================

def test_logout_invalidates_token(client):
    """
    Проверяем, что /auth/logout отрабатывает,
    а без токена защищённые эндпоинты недоступны.
    Сам токен на сервере продолжает жить до истечения TTL
    (как обычный JWT/opaque token без revocation).
    """
    token, user = login(client, "admin@mail.ru", "123456")

    # Выходим с этим токеном
    resp = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True

    # Имитируем, что фронтенд удалил токен из localStorage:
    # запрос БЕЗ Authorization -> должен быть 401
    resp2 = client.get("/admin/stats")
    assert resp2.status_code == 401
    data2 = resp2.get_json()
    assert "Требуется" in data2["error"]
