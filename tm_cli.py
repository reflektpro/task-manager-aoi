#!/usr/bin/env python
import argparse
import json
import sys
from pathlib import Path

import requests

# Базовый URL по умолчанию (может быть переопределён через --url или state)
BASE_URL = "http://localhost:5000"

# Файл, где CLI хранит токен, текущего юзера и base_url
STATE_FILE = Path(__file__).with_name(".tm_cli_state.json")


# === ХЕЛПЕРЫ ДЛЯ СОСТОЯНИЯ И ЗАПРОСОВ ===

def load_state():
    """Загрузка локального состояния (token, user, base_url)."""
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_state(state: dict):
    """Сохранение локального состояния."""
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_token_or_die():
    """Достаём токен из state, иначе подсказываем, как залогиниться."""
    state = load_state()
    token = state.get("token")
    if not token:
        print(
            "❌ Нет сохранённого токена.\n"
            "   Сначала выполни вход, например:\n"
            "   python tm_cli.py login --email admin@mail.ru --password 123456"
        )
        sys.exit(1)
    return token


def get_current_user_from_state():
    """Берём текущего пользователя из state (то, что вернуло /auth/login)."""
    state = load_state()
    user = state.get("user")
    if not user:
        print("⚠️ В state нет информации о пользователе. Выполни login ещё раз.")
        sys.exit(1)
    return user


def api_request(method: str, path: str, *, token: str | None = None,
                json_data=None, params=None):
    """
    Универсальный вызов API.

    - сам подставляет BASE_URL
    - если есть токен — добавляет Authorization
    - печатает человекочитаемую ошибку и выходит при resp.ok == False
    """
    url = BASE_URL.rstrip("/") + path
    headers = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_data is not None:
        headers["Content-Type"] = "application/json"

    resp = requests.request(method, url, headers=headers,
                            json=json_data, params=params)

    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if not resp.ok:
        msg = data.get("error") or data.get("message") or f"HTTP {resp.status_code}"
        print(f"❌ Ошибка ({resp.status_code}): {msg}")
        details = data.get("details")
        if details:
            print("  Детали:")
            if isinstance(details, list):
                for d in details:
                    print("   -", d)
            else:
                print("   ", details)
        sys.exit(1)

    return data


# === AUTH + ПРОФИЛЬ ===

def cmd_login(args):
    """Вход в систему и сохранение токена + пользователя в state."""
    payload = {"email": args.email, "password": args.password}
    data = api_request("POST", "/auth/login", json_data=payload)

    token = data.get("token")
    user = data.get("user")
    if not token or not user:
        print("⚠️ Сервер не вернул token или user, посмотри реализацию /auth/login.")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(1)

    save_state({"token": token, "user": user, "base_url": BASE_URL})
    print(
        f"✅ Успешный вход как {user.get('username')} "
        f"({user.get('email')}), роль: {user.get('role')}"
    )


def cmd_register(args):
    """Регистрация нового пользователя через /auth/register."""
    payload = {
        "email": args.email,
        "username": args.username,
        "password": args.password,
        "role": args.role,
    }
    data = api_request("POST", "/auth/register", json_data=payload)
    print("✅ Пользователь зарегистрирован:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_refresh(_args):
    """Обновление токена через /auth/refresh."""
    state = load_state()
    token = get_token_or_die()
    data = api_request("POST", "/auth/refresh", token=token)

    new_token = data.get("token") or data.get("access_token")
    user = data.get("user") or state.get("user")

    if new_token:
        state["token"] = new_token
    if user:
        state["user"] = user

    save_state(state)
    print("✅ Токен обновлён:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_logout(_args):
    """Выход и очистка локального токена."""
    state = load_state()
    token = state.get("token")
    if token:
        # Если сервер вернёт ошибку — не страшно, всё равно чистим локально
        try:
            api_request("POST", "/auth/logout", token=token)
        except SystemExit:
            pass

    save_state({})
    print("✅ Выход выполнен, локальный токен очищен.")


def cmd_me(args):
    """
    /users/me:
      * без флагов — просто показать профиль
      * с --username/--email — обновить профиль
    """
    token = get_token_or_die()

    # если указаны поля — считаем, что хотим обновление
    if args.username is not None or args.email is not None:
        payload = {}
        if args.username is not None:
            payload["username"] = args.username
        if args.email is not None:
            payload["email"] = args.email

        if not payload:
            print("⚠️ Нечего обновлять, укажи хотя бы --username или --email.")
            sys.exit(1)

        data = api_request("PUT", "/users/me", token=token, json_data=payload)
        print("✅ Профиль обновлён:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        data = api_request("GET", "/users/me", token=token)
        user = data.get("user", data)
        print("👤 Текущий пользователь:")
        print(json.dumps(user, ensure_ascii=False, indent=2))


# === ЗАДАЧИ ===

def cmd_tasks_list(args):
    """Список задач с фильтрами."""
    token = get_token_or_die()
    params = {}
    if args.status:
        params["status"] = args.status
    if args.priority:
        params["priority"] = args.priority
    if args.author_id:
        params["author_id"] = args.author_id
    if args.executor_id:
        params["executor_id"] = args.executor_id
    if args.limit:
        params["limit"] = args.limit

    data = api_request("GET", "/api/tasks", token=token, params=params)
    tasks = data.get("tasks", data)

    print(f"📋 Задачи ({len(tasks)} шт.):")
    for t in tasks:
        line = (
            f"[#{t.get('id')}] {t.get('title')} | "
            f"статус: {t.get('status')} | приоритет: {t.get('priority')}"
        )
        author = t.get("author_name") or t.get("author_id")
        exec_name = t.get("executor_name") or t.get("executor_id")
        if author:
            line += f" | автор: {author}"
        if exec_name:
            line += f" | исполнитель: {exec_name}"
        if t.get("due_date"):
            line += f" | срок: {t['due_date']}"
        print(" -", line)


def cmd_tasks_get(args):
    """Детали одной задачи по ID."""
    token = get_token_or_die()
    data = api_request("GET", f"/api/tasks/{args.id}", token=token)
    task = data.get("task", data)
    print(f"📌 Задача #{task.get('id')}:")
    print(json.dumps(task, ensure_ascii=False, indent=2))


def cmd_tasks_create(args):
    """Создать задачу от имени текущего пользователя (как автора)."""
    token = get_token_or_die()
    user = get_current_user_from_state()

    payload = {
        "title": args.title,
        "description": args.description,
        "status": args.status,
        "priority": args.priority,
        "due_date": args.due,
        "executor_id": args.executor_id,
        "author_id": user.get("id"),
    }

    data = api_request("POST", "/api/tasks", token=token, json_data=payload)
    task = data.get("task", data)
    print("✅ Задача создана:")
    print(json.dumps(task, ensure_ascii=False, indent=2))


def cmd_tasks_update(args):
    """Частично обновить задачу по ID."""
    token = get_token_or_die()
    payload = {}

    if args.title is not None:
        payload["title"] = args.title
    if args.description is not None:
        payload["description"] = args.description
    if args.status is not None:
        payload["status"] = args.status
    if args.priority is not None:
        payload["priority"] = args.priority
    if args.due is not None:
        payload["due_date"] = args.due
    if args.executor_id is not None:
        payload["executor_id"] = args.executor_id

    if not payload:
        print(
            "⚠️ Нечего обновлять. "
            "Укажи хотя бы одно поле (--title/--status/--priority/--due/--executor-id)."
        )
        sys.exit(1)

    data = api_request("PUT", f"/api/tasks/{args.id}", token=token, json_data=payload)
    task = data.get("task", data)
    print("✅ Задача обновлена:")
    print(json.dumps(task, ensure_ascii=False, indent=2))


def cmd_tasks_delete(args):
    """Удалить задачу по ID."""
    token = get_token_or_die()
    data = api_request("DELETE", f"/api/tasks/{args.id}", token=token)
    print("🗑 Результат удаления:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# === КОММЕНТАРИИ ===

def cmd_comments_list(args):
    """Список комментариев к задаче."""
    token = get_token_or_die()
    data = api_request("GET", f"/api/tasks/{args.task_id}/comments", token=token)
    comments = data.get("comments", data)

    print(f"💬 Комментарии к задаче #{args.task_id}:")
    if not comments:
        print(" (пока пусто)")
        return

    for c in comments:
        print(
            f" - [#{c.get('id')}] {c.get('author_name') or c.get('author_id')} "
            f"@ {c.get('created_at')}"
        )
        print(f"   {c.get('text')}")


def cmd_comments_add(args):
    """Добавить комментарий к задаче."""
    token = get_token_or_die()
    user = get_current_user_from_state()

    payload = {
        "text": args.text,
        "author_id": user.get("id"),
    }

    data = api_request(
        "POST",
        f"/api/tasks/{args.task_id}/comments",
        token=token,
        json_data=payload,
    )
    comment = data.get("comment", data)
    print("✅ Комментарий добавлен:")
    print(json.dumps(comment, ensure_ascii=False, indent=2))


# === АДМИНКА ===

def cmd_admin_stats(_args):
    """Посмотреть /admin/stats — общие цифры по задачам и пользователям."""
    token = get_token_or_die()
    data = api_request("GET", "/admin/stats", token=token)
    print("📊 Статистика /admin/stats:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_admin_users(_args):
    """Краткий список пользователей (по /admin/stats)."""
    token = get_token_or_die()
    data = api_request("GET", "/admin/stats", token=token)
    users = data.get("active_users", [])

    print(f"👥 Пользователи ({len(users)}):")
    for u in users:
        print(
            f" - [#{u.get('id')}] {u.get('username')} <{u.get('email')}> "
            f"роль={u.get('role')} задач={u.get('tasks_count')} комм={u.get('comments_count')}"
        )


def cmd_admin_set_role(args):
    """Поменять роль пользователя (обычно только для super_admin)."""
    token = get_token_or_die()
    payload = {"role": args.role}

    data = api_request(
        "PUT",
        f"/admin/users/{args.user_id}/role",
        token=token,
        json_data=payload,
    )
    print("✅ Роль пользователя обновлена:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_admin_delete_user(args):
    """Удалить пользователя (через /admin/users/<id>)."""
    token = get_token_or_die()
    data = api_request("DELETE", f"/admin/users/{args.user_id}", token=token)
    print("🗑 Удаление пользователя:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# === ARGPARSE / HELP ===

def build_parser():
    epilog = """\
Примеры использования:

  1) Войти под админом и посмотреть свои данные:
     tm_cli.py login --email admin@mail.ru --password 123456
     tm_cli.py me

  2) Посмотреть задачи и создать новую:
     tm_cli.py tasks list
     tm_cli.py tasks create --title "Починить тесты" --priority высокий --status "к выполнению"

  3) Обновить статус задачи и добавить комментарий:
     tm_cli.py tasks update 5 --status "выполнена"
     tm_cli.py comments add 5 --text "Сделано, проверяйте"

  4) Админские штуки:
     tm_cli.py admin stats
     tm_cli.py admin users
     tm_cli.py admin set-role 4 admin
     tm_cli.py admin delete-user 7

Короткие алиасы команд:
  login      (lg)  — вход
  logout     (lo)  — выход
  register   (rg)  — регистрация
  refresh    (rf)  — обновление токена
  me              — профиль (GET/PUT /users/me)
  tasks      (ts)  — операции с задачами
  comments   (cm)  — работа с комментариями
  admin      (ad)  — админ-панель
"""

    parser = argparse.ArgumentParser(
        prog="tm_cli.py",
        description=(
            "CLI-клиент для Task Manager API.\n"
            "Позволяет дергать основные эндпоинты без curl: логин, задачи, комментарии, админ-панель."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=epilog,
    )

    parser.add_argument(
        "--url",
        help=(
            "Базовый URL API. По умолчанию берётся из сохранённого состояния\n"
            "или 'http://localhost:5000', если ещё не логинился.\n"
            "Пример: --url http://127.0.0.1:5000"
        ),
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- auth commands ---

    p_login = subparsers.add_parser(
        "login",
        aliases=["lg"],
        help="Войти и сохранить токен.",
        description=(
            "Вход пользователя через /auth/login.\n\n"
            "Пример:\n"
            "  tm_cli.py login --email admin@mail.ru --password 123456"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_login.add_argument("--email", required=True, help="Email пользователя.")
    p_login.add_argument("--password", required=True, help="Пароль пользователя.")
    p_login.set_defaults(func=cmd_login)

    p_register = subparsers.add_parser(
        "register",
        aliases=["rg"],
        help="Регистрация нового пользователя.",
        description=(
            "Регистрация пользователя через /auth/register.\n"
            "Можно сразу указать роль (user/admin), по умолчанию user.\n\n"
            "Пример:\n"
            '  tm_cli.py register --email new@mail.ru --username "Новый" --password 123456 --role user'
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_register.add_argument("--email", required=True, help="Email нового пользователя.")
    p_register.add_argument("--username", required=True, help="Отображаемое имя пользователя.")
    p_register.add_argument("--password", required=True, help="Пароль (мин. 6 символов).")
    p_register.add_argument(
        "--role",
        choices=["user", "admin"],
        default="user",
        help="Начальная роль (user/admin), super_admin обычно создаётся вручную в БД.",
    )
    p_register.set_defaults(func=cmd_register)

    p_refresh = subparsers.add_parser(
        "refresh",
        aliases=["rf"],
        help="Обновить токен через /auth/refresh.",
        description=(
            "Обновляет токен доступа на основе текущего (хранится в state-файле).\n\n"
            "Пример:\n"
            "  tm_cli.py refresh"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_refresh.set_defaults(func=cmd_refresh)

    p_logout = subparsers.add_parser(
        "logout",
        aliases=["lo"],
        help="Выйти и удалить локальный токен.",
        description=(
            "Выход пользователя через /auth/logout (если реализован)\n"
            "и очистка локального state (токен, пользователь).\n\n"
            "Пример:\n"
            "  tm_cli.py logout"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_logout.set_defaults(func=cmd_logout)

    # --- me (/users/me) ---

    p_me = subparsers.add_parser(
        "me",
        help="Показать или обновить текущего пользователя.",
        description=(
            "Работа с эндпоинтом /users/me.\n\n"
            "Без параметров:\n"
            "  GET /users/me — показать профиль.\n\n"
            "С параметрами:\n"
            "  --username / --email — отправляется PUT /users/me для обновления.\n\n"
            "Примеры:\n"
            "  tm_cli.py me\n"
            '  tm_cli.py me --username "Новое имя"\n'
            '  tm_cli.py me --email new@mail.ru\n'
            '  tm_cli.py me --username "Новое имя" --email new@mail.ru'
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_me.add_argument("--username", help="Новое отображаемое имя.")
    p_me.add_argument("--email", help="Новый email.")
    p_me.set_defaults(func=cmd_me)

    # --- tasks ---

    p_tasks = subparsers.add_parser(
        "tasks",
        aliases=["ts"],
        help="Операции с задачами (/api/tasks).",
        description=(
            "Работа с задачами через /api/tasks.\n\n"
            "Подкоманды:\n"
            "  list    — список задач с фильтрами\n"
            "  get     — детали одной задачи\n"
            "  create  — создать задачу\n"
            "  update  — частично обновить задачу\n"
            "  delete  — удалить задачу\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    tasks_sub = p_tasks.add_subparsers(dest="tasks_cmd")

    p_tasks_list = tasks_sub.add_parser(
        "list",
        aliases=["ls"],
        help="Список задач с фильтрами.",
        description=(
            "Показать список задач с возможной фильтрацией.\n\n"
            "Фильтры:\n"
            "  --status        фильтр по статусу\n"
            "  --priority      фильтр по приоритету\n"
            "  --author-id     фильтр по id автора\n"
            "  --executor-id   фильтр по id исполнителя\n"
            "  --limit         лимит задач\n\n"
            "Примеры:\n"
            "  tm_cli.py tasks list\n"
            '  tm_cli.py ts ls --status "в процессе" --priority высокий\n'
            "  tm_cli.py tasks list --author-id 2 --limit 20"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_tasks_list.add_argument("--status", help="Фильтр по статусу.")
    p_tasks_list.add_argument("--priority", help="Фильтр по приоритету.")
    p_tasks_list.add_argument("--author-id", type=int, help="Фильтр по автору (id).")
    p_tasks_list.add_argument("--executor-id", type=int, help="Фильтр по исполнителю (id).")
    p_tasks_list.add_argument("--limit", type=int, help="Максимальное количество задач.")
    p_tasks_list.set_defaults(func=cmd_tasks_list)

    p_tasks_get = tasks_sub.add_parser(
        "get",
        aliases=["gt"],
        help="Детали задачи по ID.",
        description=(
            "Показать детали конкретной задачи через /api/tasks/<id>.\n\n"
            "Пример:\n"
            "  tm_cli.py tasks get 5\n"
            "  tm_cli.py ts gt 10"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_tasks_get.add_argument("id", type=int, help="ID задачи.")
    p_tasks_get.set_defaults(func=cmd_tasks_get)

    p_tasks_create = tasks_sub.add_parser(
        "create",
        aliases=["cr"],
        help="Создать новую задачу.",
        description=(
            "Создать задачу от имени текущего пользователя (как автора).\n\n"
            "Обязательные поля:\n"
            "  --title         заголовок задачи\n\n"
            "Опциональные:\n"
            "  --description   описание\n"
            "  --status        статус (по умолчанию 'к выполнению')\n"
            "  --priority      приоритет (низкий/средний/высокий, по умолчанию 'средний')\n"
            "  --due           срок (YYYY-MM-DD)\n"
            "  --executor-id   id исполнителя\n\n"
            "Пример:\n"
            '  tm_cli.py tasks create --title "Настроить сервер" --priority высокий --due 2025-12-31'
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_tasks_create.add_argument("--title", required=True, help="Заголовок задачи.")
    p_tasks_create.add_argument("--description", help="Описание задачи.")
    p_tasks_create.add_argument(
        "--status",
        default="к выполнению",
        help="Статус задачи (по умолчанию 'к выполнению').",
    )
    p_tasks_create.add_argument(
        "--priority",
        default="средний",
        help="Приоритет: низкий/средний/высокий (по умолчанию 'средний').",
    )
    p_tasks_create.add_argument("--due", help="Срок выполнения (формат YYYY-MM-DD).")
    p_tasks_create.add_argument("--executor-id", type=int, help="ID исполнителя задачи.")
    p_tasks_create.set_defaults(func=cmd_tasks_create)

    p_tasks_update = tasks_sub.add_parser(
        "update",
        aliases=["up"],
        help="Частичное обновление задачи.",
        description=(
            "Обновить одно или несколько полей существующей задачи.\n"
            "Отправляется PUT /api/tasks/<id> с теми полями, которые ты указал.\n\n"
            "Можно менять:\n"
            "  --title        заголовок\n"
            "  --description  описание\n"
            "  --status       статус\n"
            "  --priority     приоритет\n"
            "  --due          срок\n"
            "  --executor-id  исполнителя\n\n"
            "Примеры:\n"
            '  tm_cli.py tasks update 5 --status "в процессе"\n'
            "  tm_cli.py ts up 5 --priority высокий --executor-id 3"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_tasks_update.add_argument("id", type=int, help="ID задачи.")
    p_tasks_update.add_argument("--title", help="Новый заголовок.")
    p_tasks_update.add_argument("--description", help="Новое описание.")
    p_tasks_update.add_argument("--status", help="Новый статус.")
    p_tasks_update.add_argument("--priority", help="Новый приоритет.")
    p_tasks_update.add_argument("--due", help="Новый срок (YYYY-MM-DD).")
    p_tasks_update.add_argument("--executor-id", type=int, help="Новый исполнитель.")
    p_tasks_update.set_defaults(func=cmd_tasks_update)

    p_tasks_delete = tasks_sub.add_parser(
        "delete",
        aliases=["rm"],
        help="Удалить задачу по ID.",
        description=(
            "Удалить задачу через DELETE /api/tasks/<id>.\n\n"
            "Примеры:\n"
            "  tm_cli.py tasks delete 7\n"
            "  tm_cli.py ts rm 10"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_tasks_delete.add_argument("id", type=int, help="ID задачи.")
    p_tasks_delete.set_defaults(func=cmd_tasks_delete)

    # --- comments ---

    p_comments = subparsers.add_parser(
        "comments",
        aliases=["cm"],
        help="Работа с комментариями к задачам.",
        description=(
            "Работа с комментариями через /api/tasks/<id>/comments.\n\n"
            "Подкоманды:\n"
            "  list  — список комментариев к задаче\n"
            "  add   — добавить комментарий\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    comments_sub = p_comments.add_subparsers(dest="comments_cmd")

    p_comments_list = comments_sub.add_parser(
        "list",
        aliases=["ls"],
        help="Список комментариев к задаче.",
        description=(
            "Показать комментарии к задаче по её ID.\n\n"
            "Примеры:\n"
            "  tm_cli.py comments list 3\n"
            "  tm_cli.py cm ls 5"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_comments_list.add_argument("task_id", type=int, help="ID задачи.")
    p_comments_list.set_defaults(func=cmd_comments_list)

    p_comments_add = comments_sub.add_parser(
        "add",
        aliases=["ad"],
        help="Добавить комментарий к задаче.",
        description=(
            "Добавить комментарий к задаче от имени текущего пользователя.\n\n"
            "Примеры:\n"
            '  tm_cli.py comments add 3 --text "Сделал половину, завтра доделаю"\n'
            '  tm_cli.py cm ad 5 --text "Нужен ревью"'
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_comments_add.add_argument("task_id", type=int, help="ID задачи.")
    p_comments_add.add_argument("--text", required=True, help="Текст комментария.")
    p_comments_add.set_defaults(func=cmd_comments_add)

    # --- admin ---

    p_admin = subparsers.add_parser(
        "admin",
        aliases=["ad"],
        help="Админские действия (нужен admin/super_admin).",
        description=(
            "Админ-панель через API.\n\n"
            "Подкоманды:\n"
            "  stats       — просмотр общей статистики\n"
            "  users       — список пользователей\n"
            "  set-role    — смена роли пользователя\n"
            "  delete-user — удаление пользователя\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    admin_sub = p_admin.add_subparsers(dest="admin_cmd")

    p_admin_stats = admin_sub.add_parser(
        "stats",
        aliases=["st"],
        help="Посмотреть /admin/stats.",
        description=(
            "Запросить статистику через /admin/stats: задачи по статусам/приоритетам,\n"
            "список активных пользователей и т.п.\n\n"
            "Примеры:\n"
            "  tm_cli.py admin stats\n"
            "  tm_cli.py ad st"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_admin_stats.set_defaults(func=cmd_admin_stats)

    p_admin_users = admin_sub.add_parser(
        "users",
        aliases=["us"],
        help="Список пользователей из /admin/stats.",
        description=(
            "Вывести короткий список пользователей (id, email, роль, количество задач/комментов).\n\n"
            "Примеры:\n"
            "  tm_cli.py admin users\n"
            "  tm_cli.py ad us"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_admin_users.set_defaults(func=cmd_admin_users)

    p_admin_set_role = admin_sub.add_parser(
        "set-role",
        aliases=["sr"],
        help="Сменить роль пользователя.",
        description=(
            "Сменить роль пользователя (обычно может только super_admin).\n\n"
            "Примеры:\n"
            "  tm_cli.py admin set-role 4 admin\n"
            "  tm_cli.py ad sr 3 user"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_admin_set_role.add_argument("user_id", type=int, help="ID пользователя.")
    p_admin_set_role.add_argument(
        "role",
        choices=["user", "admin", "super_admin"],
        help="Новая роль для пользователя.",
    )
    p_admin_set_role.set_defaults(func=cmd_admin_set_role)

    p_admin_delete = admin_sub.add_parser(
        "delete-user",
        aliases=["du"],
        help="Удалить пользователя.",
        description=(
            "Удалить пользователя через /admin/users/<id>.\n\n"
            "Примеры:\n"
            "  tm_cli.py admin delete-user 7\n"
            "  tm_cli.py ad du 5"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_admin_delete.add_argument("user_id", type=int, help="ID пользователя.")
    p_admin_delete.set_defaults(func=cmd_admin_delete_user)

    return parser


def main():
    global BASE_URL
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    state = load_state()
    if args.url:
        BASE_URL = args.url
    elif "base_url" in state:
        BASE_URL = state["base_url"]

    args.func(args)


if __name__ == "__main__":
    main()
