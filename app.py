# app.py
from flask import Flask, request, jsonify, Response, g, render_template,send_from_directory
import json
import database
from utils.validators import validate_email, validate_username, validate_task_data
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
from cache import (
    make_task_list_cache_key,
    get_cached_task_list,
    set_cached_task_list,
    get_cached_task_detail,
    set_cached_task_detail,
    invalidate_task_list_cache,
    invalidate_task_detail,
)
from flask_socketio import SocketIO
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif",
    "pdf", "txt", "doc", "docx",
    "xls", "xlsx", "zip", "rar"
}
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
app.config["SECRET_KEY"] = "very-secret-key-change-me" 
app.config["JSON_AS_ASCII"] = False  # чтобы JSON отдавался с нормальной кириллицей

# ===== ОБРАБОТЧИКИ ОШИБОК =====
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Ресурс не найден"}), 404


@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Некорректный запрос"}), 400


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500

# ========== ТОКЕНЫ =================
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        parts = auth_header.split()

        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify({"error": "Требуется токен авторизации (Authorization: Bearer <token>)"}), 401

        token = parts[1]

        user = database.get_user_by_token(token)
        if not user:
            return jsonify({"error": "Недействительный или истёкший токен"}), 401

        g.current_user = user
        return f(*args, **kwargs)
    return decorated





# ===== ГЛАВНАЯ СТРАНИЦА =====
@app.route('/')
def home():
    payload = {
        "project": "Task Manager API",
        "version": "1.3",
        "description": "REST API для управления задачами с ролями пользователей и админ-панелью.",
        "endpoints": {
            "auth": {
                "POST /auth/register": "Регистрация пользователя (user/admin; super_admin только через БД)",
                "POST /auth/login": "Авторизация, возвращает token",
                "POST /auth/refresh": "Обновление токена (refresh → новый access)",
                "POST /auth/logout": "Выход, инвалидация текущего токена"
            },
            "users": {
                "GET /api/users": "Список пользователей (для отладки)",
                "GET /api/users/<id>": "Пользователь по ID",
                "GET /users/me": "Профиль текущего пользователя (по токену)",
                "PUT /users/me": "Обновление текущего пользователя (без пароля)"
            },
            "tasks": {
                "GET /api/tasks": "Список задач (фильтры: status, priority, author_id, executor_id, limit, offset)",
                "GET /api/tasks/<id>": "Детали задачи",
                "POST /api/tasks": "Создание задачи (роль admin или super_admin)",
                "PUT /api/tasks/<id>": "Обновление задачи (admin — только свои, super_admin — любые)",
                "DELETE /api/tasks/<id>": "Удаление задачи (admin — только свои, super_admin — любые)"
            },
            "comments": {
                "GET /api/tasks/<id>/comments": "Комментарии к задаче",
                "POST /api/tasks/<id>/comments": "Добавить комментарий (любой авторизованный пользователь)",
                "PUT /api/comments/<id>": "Обновить комментарий (автор, admin, super_admin)",
                "DELETE /api/comments/<id>": "Удалить комментарий (автор, admin, super_admin)"
            },
            "admin_panel": {
                "GET /admin": "HTML админ-панель (логин, задачи, пользователи, статистика)",
                "GET /admin/stats": "JSON статистика (задачи по статусам, активность пользователей)",
                "PUT /admin/users/<id>/role": "Изменение роли пользователя (только super_admin)",
                "DELETE /admin/users/<id>": "Удаление пользователя (только super_admin)"
            }
        }
    }

    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json"
    )



# ===== ПОЛЬЗОВАТЕЛИ =====
@app.route('/api/users', methods=['GET'])
def get_users():
    """Получить всех пользователей"""
    users = database.get_all_users()
    return jsonify({
        "success": True,
        "count": len(users),
        "users": users
    })


@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    """Получить пользователя по ID"""
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404

    return jsonify({
        "success": True,
        "user": user
    })


# ===== ЗАДАЧИ =====
@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Получить все задачи с фильтрацией"""
    filters = {}

    # Простые фильтры
    for param in ['status', 'priority', 'author_id', 'executor_id']:
        value = request.args.get(param)
        if value:
            filters[param] = value

    # Фильтры по дате
    due_date_before = request.args.get('due_date_before')
    due_date_after = request.args.get('due_date_after')

    if due_date_before:
        filters['due_date_before'] = due_date_before
    if due_date_after:
        filters['due_date_after'] = due_date_after

    # Пагинация
    try:
        limit = int(request.args.get('limit', 100))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
    except ValueError:
        return jsonify({"error": "Параметры limit и page должны быть числами"}), 400

    # ----- КЭШ СПИСКА ЗАДАЧ -----
    cache_key = make_task_list_cache_key(filters, page, limit)
    cached = get_cached_task_list(cache_key)
    if cached is not None:
        # Возвращаем из кэша, структура ответа такая же
        return jsonify({
            "success": True,
            "count": cached["count"],
            "page": page,
            "limit": limit,
            "tasks": cached["tasks"],
        })

    # Если в кэше нет — идём в БД
    tasks = database.get_all_tasks(filters, limit, offset)
    data_for_cache = {
        "count": len(tasks),
        "tasks": tasks,
    }
    set_cached_task_list(cache_key, data_for_cache)

    return jsonify({
        "success": True,
        "count": data_for_cache["count"],
        "page": page,
        "limit": limit,
        "tasks": data_for_cache["tasks"],
    })

# ==== WebSocket / Socket.IO уведомления ====

def broadcast_task_event(event_type: str, task: dict | None = None, task_id: int | None = None):
    """
    Рассылаем событие про задачу всем подключённым клиентам.
    event_type: 'created' | 'updated' | 'deleted'
    """
    payload = {"type": event_type}
    if task is not None:
        payload["task"] = task
    if task_id is not None:
        payload["task_id"] = task_id

    # БЕЗ broadcast=...
    socketio.emit("task_event", payload)


def broadcast_comment_event(
    event_type: str,
    comment: dict | None = None,
    task_id: int | None = None,
    comment_id: int | None = None
):
    """
    Рассылаем событие про комментарий.
    event_type: 'created' | 'updated' | 'deleted'
    """
    payload = {"type": event_type}
    if comment is not None:
        payload["comment"] = comment
    if task_id is not None:
        payload["task_id"] = task_id
    if comment_id is not None:
        payload["comment_id"] = comment_id

    socketio.emit("comment_event", payload)



@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """Получить задачу по ID (с кэшированием деталей)"""
    # Пробуем взять из кэша
    task = get_cached_task_detail(task_id)
    if task is None:
        # Если в кэше нет — идём в БД
        task = database.get_task_by_id(task_id)
        if not task:
            return jsonify({"error": "Задача не найден"}), 404
        # Кладём в кэш
        set_cached_task_detail(task_id, task)

    return jsonify({
        "success": True,
        "task": task
    })



@app.route('/api/tasks', methods=['POST'])
@token_required
def create_task():
    """Создать новую задачу (только для admin / super_admin)"""
    # Проверка роли
    user = g.current_user
    if user.get("role") not in ("admin", "super_admin"):
        return jsonify({"error": "Недостаточно прав для создания задач"}), 403

    try:
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "Нужен JSON в теле запроса"}), 400

        # Валидация данных задачи (для создания — require_all=True)
        errors = validate_task_data(data, require_all=True)
        if errors:
            return jsonify({"error": "Ошибки валидации", "details": errors}), 400

        title = data.get('title', '').strip()
        description = (data.get('description') or '').strip()
        author_id = data.get('author_id')
        executor_id = data.get('executor_id') or author_id  # по умолчанию автор
        status = data.get('status') or 'к выполнению'
        priority = data.get('priority') or 'средний'
        due_date = data.get('due_date')

        # Создаём задачу через модуль database
        task_id = database.create_task(
            title=title,
            description=description,
            author_id=author_id,
            executor_id=executor_id,
            status=status,
            priority=priority,
            due_date=due_date
        )

        # Получаем её в "расширенном" виде (c author_name, executor_name)
        task = database.get_task_by_id(task_id)
        broadcast_task_event("created", task=task)  
        if not task:
            return jsonify({"error": "Не удалось получить задачу после создания"}), 500

        # Инвалидация тут
        invalidate_task_list_cache()
        invalidate_task_detail(task_id)

        return jsonify({
            "success": True,
            "message": "Задача создана",
            "task": task
        }), 201
    
    except sqlite3.IntegrityError as e:
        return jsonify({"error": f"Ошибка базы данных: {str(e)}"}), 400
    except Exception as e:
        print(f"Ошибка в create_task: {e}")
        return jsonify({"error": f"Внутренняя ошибка: {str(e)}"}), 500


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@token_required
def update_task(task_id):
    """Обновить задачу"""
    # Кто делает запрос
    current_user, error = resolve_current_user()
    if error:
        return jsonify({"error": error}), 401

    role = current_user["role"]

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"error": "Необходимы данные для обновления"}), 400

    # Проверяем, что задача существует
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404

    # --- ПРОВЕРКА ПРАВ СООТВЕТСТВУЕТ ТЗ ---
    # Обычный юзер вообще не может обновлять задачи
    if role == "user":
        return jsonify({"error": "Недостаточно прав"}), 403

    # Админ может трогать только задачи, где он автор
    if role == "admin" and task["author_id"] != current_user["id"]:
        return jsonify({
            "error": "Администратор может изменять только свои задачи"
        }), 403
    # super_admin проходит дальше без ограничений

    # Разрешённые к обновлению поля
    allowed_fields = ['title', 'description', 'status', 'priority', 'due_date', 'executor_id']

    filtered_data = {
        key: value
        for key, value in data.items()
        if key in allowed_fields
    }

    if not filtered_data:
        return jsonify({
            "error": "Нет допустимых полей для обновления",
            "allowed_fields": allowed_fields
        }), 400

    # Частичная валидация (require_all=False)
    errors = validate_task_data(filtered_data, require_all=False)
    if errors:
        return jsonify({"error": "Ошибки валидации", "details": errors}), 400

    # ВАЖНО: в базу отправляем только отфильтрованные поля
    success = database.update_task(task_id, **filtered_data)
    if not success:
        return jsonify({"error": "Не удалось обновить задачу"}), 400

    # Инвалидируем кэш
    invalidate_task_list_cache()
    invalidate_task_detail(task_id)

    updated_task = database.get_task_by_id(task_id)
    broadcast_task_event("updated", task=updated_task)

    return jsonify({
        "success": True,
        "message": "Задача обновлена",
        "task": updated_task
    }), 200


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@token_required
def delete_task(task_id):
    """Удалить задачу"""
    # Кто делает запрос
    current_user, error = resolve_current_user()
    if error:
        return jsonify({"error": error}), 401

    role = current_user["role"]

    # Сначала найдём задачу через твой database-слой
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404

    # --- ПРОВЕРКА ПРАВ ---
    if role == "user":
        return jsonify({"error": "Недостаточно прав"}), 403

    if role == "admin" and task["author_id"] != current_user["id"]:
        return jsonify({
            "error": "Администратор может удалять только свои задачи"
        }), 403
    # super_admin снова проходит дальше

    # Дальше можно оставить твой старый sqlite-код
    try:
        import sqlite3
        conn = sqlite3.connect('task_manager.db')
        cursor = conn.cursor()

        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected:
            invalidate_task_list_cache()
            invalidate_task_detail(task_id)
            broadcast_task_event("deleted", task_id=task_id)

        return jsonify({
            "success": True,
            "message": f"Задача #{task_id} удалена",
            "deleted": affected
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ===== КОММЕНТАРИИ =====
@app.route('/api/tasks/<int:task_id>/comments', methods=['GET'])
def get_task_comments(task_id):
    """Получить комментарии к задаче"""
    # Проверяем существует ли задача
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404

    comments = database.get_comments_by_task(task_id)

    return jsonify({
        "success": True,
        "count": len(comments),
        "task_id": task_id,
        "comments": comments
    })


@app.route('/api/tasks/<int:task_id>/comments', methods=['POST'])
def add_comment_to_task(task_id):
    """Простая версия добавления комментария (пока без валидатора)"""
    try:
        data = request.get_json(silent=True)

        if data is None:
            return jsonify({"error": "Нужен JSON в теле запроса"}), 400

        if 'text' not in data:
            return jsonify({"error": "Нужно поле 'text'"}), 400
        if 'author_id' not in data:
            return jsonify({"error": "Нужно поле 'author_id'"}), 400

        text = str(data['text']).strip()
        author_id = data['author_id']

        if not text:
            return jsonify({"error": "Текст комментария не может быть пустым"}), 400

        # Проверяем, что задача существует
        task = database.get_task_by_id(task_id)
        if not task:
            return jsonify({"error": "Задача не найдена"}), 404

        # Добавляем комментарий в БД
        comment_id = database.add_comment(task_id=task_id, author_id=author_id, text=text)
        new_comment = database.get_comment_by_id(comment_id)
        broadcast_comment_event("created", comment=new_comment, task_id=task_id)    

        return jsonify({
            "success": True,
            "message": "Комментарий добавлен",
            "comment": {
                "id": comment_id,
                "task_id": task_id,
                "author_id": author_id,
                "text": text
            }
        }), 201

    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    """Удалить комментарий"""
    try:
        conn = sqlite3.connect('task_manager.db')
        cursor = conn.cursor()

        # Проверяем существует ли комментарий
        cursor.execute("SELECT id FROM comments WHERE id = ?", (comment_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Комментарий не найден"}), 404

        task_id = row[0]

        cursor.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        if affected:
            # уведомляем фронт
            broadcast_comment_event(
                "deleted",
                task_id=task_id,
                comment_id=comment_id
            )

        return jsonify({
            "success": True,
            "message": f"Комментарий #{comment_id} удалён",
            "deleted": affected
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def get_comment_by_id(comment_id):
    """Получить один комментарий по ID"""
    with get_db() as cursor:
        cursor.execute('''
        SELECT 
            c.id,
            c.task_id,
            c.author_id,
            c.text,
            c.created_at,
            u.username as author_name
        FROM comments c
        JOIN users u ON c.author_id = u.id
        WHERE c.id = ?
        ''', (comment_id,))
        return dict_from_row(cursor.fetchone())


@app.route('/api/comments/<int:comment_id>', methods=['PUT'])
@token_required
def update_comment_route(comment_id):
    """Обновить комментарий по ID"""
    data = request.get_json(silent=True) or {}
    new_text = (data.get("text") or "").strip()

    if not new_text:
        return jsonify({"error": "Нужно непустое поле 'text'"}), 400

    # Проверяем, что комментарий существует
    comment = database.get_comment_by_id(comment_id)
    if not comment:
        return jsonify({"error": "Комментарий не найден"}), 404

    # Проверяем права: автор комментария или админ/суперадмин
    user = g.current_user
    is_admin = user.get("role") in ("admin", "super_admin")
    if not is_admin and comment["author_id"] != user["id"]:
        return jsonify({"error": "Недостаточно прав для редактирования комментария"}), 403

    ok = database.update_comment(comment_id, new_text)
    if not ok:
        return jsonify({"error": "Не удалось обновить комментарий"}), 500

    updated = database.get_comment_by_id(comment_id)
    broadcast_comment_event("updated", comment=updated, task_id=updated["task_id"])

    return jsonify({
        "success": True,
        "message": "Комментарий обновлён",
        "comment": updated
    }), 200




# ===== АУТЕНТИФИКАЦИЯ =====
@app.route('/auth/login', methods=['POST'])
def login():
    """Авторизация по email и паролю с выдачей токена из БД."""
    data = request.get_json(silent=True) or {}

    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({
            "success": False,
            "error": "Нужны email и password"
        }), 400

    user = database.get_user_by_email(email)
    if not user:
        return jsonify({
            "success": False,
            "error": "Неверный email или пароль"
        }), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({
            "success": False,
            "error": "Неверный email или пароль"
        }), 401

    user_public = {
        "id": user["id"],
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
    }

    access_token = database.create_auth_token(user["id"])

    return jsonify({
        "success": True,
        "message": "Авторизация успешна",
        "user": user_public,
        "token": access_token
    }), 200

@app.route('/auth/logout', methods=['POST'])
@token_required
def logout():
    token = getattr(g, "current_token", None)
    if not token:
        return jsonify({"success": True, "message": "Уже разлогинен"}), 200

    database.delete_access_token(token)
    return jsonify({"success": True, "message": "Выход выполнен"}), 200
    

@app.route('/auth/register', methods=['POST'])
def register():
    """Регистрация нового пользователя"""
    data = request.get_json(silent=True) or {}

    email = (data.get('email') or '').strip()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    role = data.get('role') or 'user'  # по умолчанию обычный пользователь

    errors = []

    # Валидация email и username через наши валидаторы
    for err in validate_email(email):
        errors.append(f"Email: {err}")
    for err in validate_username(username):
        errors.append(f"Username: {err}")

    # Простая проверка пароля
    if len(password) < 6:
        errors.append("Пароль должен быть не короче 6 символов")

    # Роль (на всякий случай)
    if role not in ('user', 'admin', 'super_admin'):
        errors.append("Недопустимая роль пользователя")

    if errors:
        print("DEBUG /auth/register data:", data)
        print("DEBUG /auth/register errors:", errors)
        return jsonify({
            "error": "Ошибки валидации",
            "details": errors
        }), 400

    # Проверяем, нет ли уже такого email
    existing = database.get_user_by_email(email)
    if existing:
        return jsonify({
            "error": "Пользователь с таким email уже существует"
        }), 400

    # Хэшируем пароль
    password_hash = generate_password_hash(password)

    # Пишем в БД
    user_id = database.create_user(email, username, password_hash, role=role)
    if not user_id:
        return jsonify({"error": "Не удалось создать пользователя"}), 500

    return jsonify({
        "success": True,
        "message": "Пользователь зарегистрирован",
        "user": {
            "id": user_id,
            "email": email,
            "username": username,
            "role": role
        }
    }), 201



@app.route('/users/me', methods=['GET'])
@token_required
def get_current_user():
    """Профиль текущего пользователя на основе токена."""
    user = g.current_user
    return jsonify({
        "success": True,
        "user": user
    }), 200

def resolve_current_user():
    """Достаём пользователя из заголовка Authorization: Bearer <token>"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        # нет заголовка — гость
        return None, None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None, (jsonify({"error": "Некорректный токен"}), 401)

    user = database.get_user_by_access_token(token)
    if not user:
        return None, (jsonify({"error": "Требуется авторизация"}), 401)

    # Кладём в g, чтобы все хендлеры могли пользоваться
    g.current_user = user
    g.current_token = token
    return user, None

def auth_required(fn):
    """Декоратор: нужен авторизованный пользователь."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user, error = resolve_current_user()
        if error is not None:
            # error уже (Response, code) — просто возвращаем
            return error
        if user is None:
            return jsonify({"error": "Требуется авторизация"}), 401
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    """Декоратор: нужен admin или super_admin."""


    @wraps(fn)
    @auth_required
    def wrapper(*args, **kwargs):
        user = g.current_user
        if user["role"] not in ("admin", "super_admin"):
            return jsonify({"error": "Недостаточно прав"}), 403
        return fn(*args, **kwargs)

    return wrapper


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user, error = resolve_current_user()
        if error:
            message, code = error
            return jsonify({"error": message}), code
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user, error = resolve_current_user()
        if error:
            message, code = error
            return jsonify({"error": message}), code
        
        if user["role"] not in ("admin", "super_admin"):
            return jsonify({"error": "Недостаточно прав"}), 403
        
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def super_admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user, error = resolve_current_user()
        if error:
            message, code = error
            return jsonify({"error": message}), code
        
        if user["role"] != "super_admin":
            return jsonify({"error": "Только супер-админ может выполнить это действие"}), 403
        
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper



@app.route('/users/me', methods=['PUT'])
@token_required
def update_current_user():
    """Обновление профиля (пока только username, без записи в БД)."""
    data = request.get_json(silent=True) or {}

    if 'username' not in data:
        return jsonify({"error": "Нужно поле 'username'"}), 400

    new_username = (data['username'] or "").strip()
    if not new_username:
        return jsonify({"error": "Имя пользователя не может быть пустым"}), 400

    return jsonify({
        "success": True,
        "message": "Профиль обновлён",
        "updated": {
            "username": new_username
        }
    }), 200

# ===== ОБРАБОТКА ФАЙЛОВ =====
@app.route("/api/tasks/<int:task_id>/files", methods=["GET"])
def list_task_files(task_id):
    """Список вложений для задачи"""
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404

    attachments = database.get_attachments_for_task(task_id)
    return jsonify({
        "success": True,
        "files": attachments
    })

@app.route('/api/tasks/<int:task_id>/files', methods=['POST'])
@token_required
def upload_task_files(task_id):
    """
    Загрузка одного или нескольких файлов к задаче.
    Поле формы: files (может быть несколько).
    """
    current_user = g.current_user  
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404
    if current_user["role"] not in ("admin", "super_admin"):
        return jsonify({"error": "Недостаточно прав для загрузки файлов"}), 403
    if "files" not in request.files:
        return jsonify({"error": "Ожидается поле 'files' в multipart-форме"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Файлы не переданы"}), 400
    upload_dir = os.path.join(app.root_path, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []

    for file_storage in files:
        if not file_storage or file_storage.filename == "":
            continue

        original_name = secure_filename(file_storage.filename)
        if not original_name:
            continue

        _, ext = os.path.splitext(original_name)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        disk_path = os.path.join(upload_dir, stored_name)

        file_storage.stream.seek(0, os.SEEK_END)
        size_bytes = file_storage.stream.tell()
        file_storage.stream.seek(0)

        file_storage.save(disk_path)

        file_id = database.save_task_file(
            task_id=task_id,
            original_name=original_name,
            stored_name=stored_name,
            content_type=file_storage.mimetype,
            size_bytes=size_bytes,
            uploader_id=current_user["id"],
        )

        saved_files.append(
            {
                "id": file_id,
                "task_id": task_id,
                "original_name": original_name,
                "stored_name": stored_name,
                "content_type": file_storage.mimetype,
                "size_bytes": size_bytes,
            }
        )

    if not saved_files:
        return jsonify({"error": "Не удалось сохранить ни один файл"}), 400

    return jsonify(
        {
            "success": True,
            "message": f"Загружено файлов: {len(saved_files)}",
            "files": saved_files,
        }
    ), 201


@app.route("/api/files/<int:attachment_id>/download", methods=["GET"])
def download_attachment(attachment_id):
    """Скачать файл-вложение"""
    attachment = database.get_attachment_by_id(attachment_id)
    if not attachment:
        return jsonify({"error": "Файл не найден"}), 404

    stored_name = attachment["filename_stored"]
    original_name = attachment["filename_orig"]
    directory = app.config["UPLOAD_FOLDER"]

    file_path = os.path.join(directory, stored_name)
    if not os.path.exists(file_path):
        return jsonify({"error": "Файл отсутствует на диске"}), 404

    return send_from_directory(
        directory,
        stored_name,
        as_attachment=True,
        download_name=original_name,
    )

@app.route("/api/files/<int:attachment_id>", methods=["DELETE"])
@token_required
def delete_attachment(attachment_id):
    user = g.current_user
    """Удалить вложение"""
    attachment = database.get_attachment_by_id(attachment_id)
    if not attachment:
        return jsonify({"error": "Файл не найден"}), 404

    # Проверка прав
    role = user.get("role")
    is_owner = user["id"] == attachment["uploader_id"]
    is_admin = role in ("admin", "super_admin")

    if not (is_owner or is_admin):
        return jsonify({"error": "Недостаточно прав для удаления файла"}), 403

    stored_name = attachment["filename_stored"]
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_name)

    ok = database.delete_attachment(attachment_id)
    if not ok:
        return jsonify({"error": "Не удалось удалить запись о файле"}), 400

    # Пытаемся удалить сам файл с диска
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        # в крайнем случае просто пишем в лог, но ошибкой не считаем
        print(f"⚠ Не удалось удалить файл с диска: {file_path}", flush=True)

    return jsonify({
        "success": True,
        "message": f"Файл #{attachment_id} удалён"
    })

# ===== АДМИН: УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ =====

@app.route('/admin/stats', methods=['GET'])
@token_required
def admin_stats():
    """Статистика для админ-панели (только admin / super_admin)."""
    user = g.current_user
    if user.get("role") not in ("admin", "super_admin"):
        return jsonify({"error": "Недостаточно прав"}), 403

    stats = database.get_task_stats()
    active_users = database.get_active_users(limit=10)

    return jsonify({
        "success": True,
        "stats": stats,
        "active_users": active_users,
    })

@app.route('/admin')
def admin_panel():
    """
    Простейшая админ-панель с UI.
    Страница, которая через JS ходит в API: /auth/login, /admin/stats, /api/tasks, /api/users.
    """
    return render_template('admin.html')

@app.route('/admin/users/<int:user_id>/role', methods=['PUT'])
@super_admin_required
def admin_change_user_role(user_id):
    data = request.get_json(silent=True) or {}
    new_role = data.get("role")

    if new_role not in ("user", "admin", "super_admin"):
        return jsonify({"error": "Недопустимая роль"}), 400

    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404

    # нельзя менять роль самому себе с super_admin на что-то другое (по желанию)
    if g.current_user["id"] == user_id and new_role != "super_admin":
        return jsonify({"error": "Нельзя понизить самого себя"}), 400

    with database.get_db() as cursor:
        cursor.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (new_role, user_id)
        )
        if cursor.rowcount == 0:
            return jsonify({"error": "Не удалось обновить роль"}), 500

    return jsonify({
        "success": True,
        "user_id": user_id,
        "new_role": new_role
    })

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@super_admin_required
def admin_delete_user(user_id):
    # нельзя удалить сам себя
    if g.current_user["id"] == user_id:
        return jsonify({"error": "Нельзя удалить самого себя"}), 400

    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404

    try:
        deleted = database.delete_user(user_id)
    except Exception as e:
        # сюда может прилететь FOREIGN KEY constraint failed
        return jsonify({
            "error": "Не удалось удалить пользователя",
            "details": str(e)
        }), 400

    if not deleted:
        return jsonify({"error": "Пользователь не был удалён"}), 500

    return jsonify({
        "success": True,
        "deleted_id": user_id
    })

@app.route("/admin/users/<int:user_id>", methods=["PUT"])
@token_required
def admin_update_user(user_id):
    current_user, error = resolve_current_user()
    if error:
        return jsonify({"error": error}), 401

    if current_user["role"] != "super_admin":
        return jsonify({
            "error": "Только супер-админ может выполнить это действие"
        }), 403

@app.route('/auth/refresh', methods=['POST'])
def refresh_token():
    """Обновить токен авторизации: старый инвалидируется, выдаётся новый."""
    data = request.get_json(silent=True) or {}
    old_token = (data.get("token") or "").strip()

    if not old_token:
        return jsonify({"error": "Нужен токен для обновления"}), 400

    new_token = database.refresh_token(old_token)
    if not new_token:
        return jsonify({"error": "Токен недействителен или истёк"}), 401

    return jsonify({
        "success": True,
        "token": new_token
    }), 200


# ======= БАНЕР =====================
def print_banner():
    line = "=" * 80
    print(line)
    print("TASK MANAGER API".center(80))
    print(line)
    print("Базовый URL: http://localhost:5000")
    print()

    print("Аутентификация:")
    print("  POST /auth/register          - регистрация пользователя")
    print("  POST /auth/login             - логин, выдаёт токен")
    print("  POST /auth/refresh           - обновление токена")
    print("  POST /auth/logout            - выход, токен становится невалиден")
    print()

    print("Пользователи:")
    print("  GET  /api/users              - список пользователей (отладка)")
    print("  GET  /api/users/<id>         - пользователь по ID")
    print("  GET  /users/me               - профиль текущего пользователя")
    print("  PUT  /users/me               - обновление текущего пользователя")
    print()

    print("Задачи:")
    print("  GET    /api/tasks            - список задач (фильтры: status, priority, author_id, executor_id)")
    print("  GET    /api/tasks/<id>       - детали задачи")
    print("  POST   /api/tasks            - создать задачу (admin / super_admin)")
    print("  PUT    /api/tasks/<id>       - обновить задачу (admin свои, super_admin любые)")
    print("  DELETE /api/tasks/<id>       - удалить задачу (admin свои, super_admin любые)")
    print()

    print("Комментарии:")
    print("  GET    /api/tasks/<id>/comments   - комментарии к задаче")
    print("  POST   /api/tasks/<id>/comments   - добавить комментарий")
    print("  PUT    /api/comments/<id>         - обновить комментарий")
    print("  DELETE /api/comments/<id>         - удалить комментарий")
    print()

    print("Админ-панель:")
    print("  GET  /admin                  - HTML панель (логин, задачи, пользователи, статистика)")
    print("  GET  /admin/stats            - JSON статистика")
    print("  PUT  /admin/users/<id>/role  - смена роли пользователя (super_admin)")
    print("  DELETE /admin/users/<id>     - удалить пользователя (super_admin)")
    print(line)



# ===== ЗАПУСК СЕРВЕРА =====
if __name__ == '__main__':
    print_banner()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
