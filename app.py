# app.py
from flask import Flask, request, jsonify
import database
# Удали или закомментируй импорт выше
# from utils.validators import validate_email, validate_username, validate_task_data

# Вместо этого добавь простые функции перед @app.route:
import re
from datetime import datetime

# Простейшие функции валидации (всегда возвращают True/пустой список)
def validate_email(email):
    """Минимальная проверка email"""
    return True  # всегда OK

def validate_username(username):
    """Минимальная проверка имени"""
    return True  # всегда OK

def validate_task_data(data, require_all=False):
    """Минимальная валидация задачи"""
    errors = []
    
    if require_all:
        if not data.get('title'):
            errors.append("Нужен заголовок")
        if not data.get('author_id'):
            errors.append("Нужен автор")
    
    return errors

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

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

# ===== ГЛАВНАЯ СТРАНИЦА =====
@app.route('/')
def home():
    return jsonify({
        "project": "Task Manager API",
        "version": "1.0",
        "endpoints": {
            "users": {
                "GET /api/users": "Все пользователи",
                "GET /api/users/<id>": "Пользователь по ID"
            },
            "tasks": {
                "GET /api/tasks": "Все задачи (с фильтрами)",
                "GET /api/tasks/<id>": "Задача по ID",
                "POST /api/tasks": "Создать задачу",
                "PUT /api/tasks/<id>": "Обновить задачу"
            },
            "comments": {
                "GET /api/tasks/<id>/comments": "Комментарии к задаче",
                "POST /api/tasks/<id>/comments": "Добавить комментарий"
            }
        }
    })

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
    # Получаем параметры фильтрации из запроса
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
    
    # Получаем задачи
    tasks = database.get_all_tasks(filters, limit, offset)
    
    return jsonify({
        "success": True,
        "count": len(tasks),
        "page": page,
        "limit": limit,
        "tasks": tasks
    })

@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """Получить задачу по ID"""
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найден"}), 404
    
    return jsonify({
        "success": True,
        "task": task
    })

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Создать новую задачу"""
    try:
        data = request.get_json(silent=True)
        
        print("="*60)
        print("DEBUG: Получен POST запрос")
        print(f"Data: {data}")
        print(f"Type: {type(data)}")
        print("="*60)
        
        # Проверяем что данные пришли
        if data is None:
            return jsonify({"error": "Нужен JSON в теле запроса"}), 400
        
        # Проверяем обязательные поля
        if 'title' not in data:
            return jsonify({"error": "Нужно поле 'title'"}), 400
        if 'author_id' not in data:
            return jsonify({"error": "Нужно поле 'author_id'"}), 400
        
        # Получаем значения (с defaults)
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        author_id = data.get('author_id')
        executor_id = data.get('executor_id', author_id)  # по умолчанию тот же автор
        status = data.get('status', 'к выполнению')
        priority = data.get('priority', 'средний')
        due_date = data.get('due_date')
        
        # Подключаемся к БД
        import sqlite3
        conn = sqlite3.connect('task_manager.db')
        cursor = conn.cursor()
        
        # Вставляем задачу
        cursor.execute('''
        INSERT INTO tasks 
        (title, description, status, priority, due_date, author_id, executor_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, description, status, priority, due_date, author_id, executor_id))
        
        task_id = cursor.lastrowid
        # ПОЛУЧАЕМ СОЗДАННУЮ ЗАДАЧУ С ПРАВИЛЬНЫМИ ИМЕНАМИ:
        cursor.execute('''
        SELECT 
            t.id, t.title, t.description, t.status, t.priority, t.due_date,
            t.author_id, t.executor_id, t.created_at, t.updated_at,
            u1.username as author_name,
            u2.username as executor_name
        FROM tasks t
        LEFT JOIN users u1 ON t.author_id = u1.id
        LEFT JOIN users u2 ON t.executor_id = u2.id
        WHERE t.id = ?
        ''', (task_id,))
        
        task = cursor.fetchone()
        
        if task:
            # ПРАВИЛЬНОЕ ПРЕОБРАЗОВАНИЕ:
            task_dict = {
                "id": task[0],
                "title": task[1],
                "description": task[2],
                "status": task[3],
                "priority": task[4],
                "due_date": task[5],
                "author_id": task[6],
                "executor_id": task[7],
                "created_at": task[8],
                "updated_at": task[9],
                "author_name": task[10],    # ← username из users
                "executor_name": task[11]   # ← username из users
            }
            
            return jsonify({
                "success": True,
                "message": "Задача создана",
                "task": task_dict
            }), 201        
        conn.commit()
        
        # Получаем созданную задачу для ответа
        cursor.execute('''
        SELECT t.*, 
               u1.username as author_name,
               u2.username as executor_name
        FROM tasks t
        LEFT JOIN users u1 ON t.author_id = u1.id
        LEFT JOIN users u2 ON t.executor_id = u2.id
        WHERE t.id = ?
        ''', (task_id,))
        
        task = cursor.fetchone()
        conn.close()
        
        if task:
            # Преобразуем в словарь
            task_dict = {
                "id": task[0],
                "title": task[1],
                "description": task[2],
                "status": task[3],
                "priority": task[4],
                "due_date": task[5],
                "author_id": task[6],
                "executor_id": task[7],
                "author_name": task[8],
                "executor_name": task[9]
            }
            
            return jsonify({
                "success": True,
                "message": "Задача создана",
                "task": task_dict
            }), 201
        else:
            return jsonify({"error": "Не удалось создать задачу"}), 500
            
    except sqlite3.IntegrityError as e:
        return jsonify({"error": f"Ошибка базы данных: {str(e)}"}), 400
    except Exception as e:
        print(f"Ошибка в create_task: {e}")
        return jsonify({"error": f"Внутренняя ошибка: {str(e)}"}), 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """Обновить задачу"""
    data = request.get_json(silent=True) or {}

    if not data:
        return jsonify({"error": "Необходимы данные для обновления"}), 400

    # Проверяем существует ли задача
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404

    # Разрешённые к обновлению поля (синхронно с database.update_task)
    allowed_fields = ['title', 'description', 'status', 'priority', 'due_date', 'executor_id']

    # Оставляем только разрешённые поля
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

    # Валидация (сейчас у тебя заглушка, но оставляем на будущее)
    errors = validate_task_data(filtered_data, require_all=False)
    if errors:
        return jsonify({"error": "Ошибки валидации", "details": errors}), 400

    # Обновляем задачу
    success = database.update_task(task_id, **filtered_data)

    if not success:
        return jsonify({"error": "Не удалось обновить задачу"}), 400

    # Получаем обновлённую задачу
    updated_task = database.get_task_by_id(task_id)

    return jsonify({
        "success": True,
        "message": "Задача обновлена",
        "task": updated_task
    }), 200

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
    """Простая версия добавления комментария"""
    try:
        # Пробуем получить JSON
        data = request.get_json(silent=True)
        
        if data is None:  # Если JSON невалидный
            # Пробуем получить как сырые данные
            raw_data = request.data
            if raw_data:
                try:
                    import json
                    data = json.loads(raw_data.decode('utf-8'))
                except:
                    return jsonify({"error": "Некорректный JSON"}), 400
        
        if not data:
            return jsonify({"error": "Нужны данные в формате JSON"}), 400
        
        print(f"DEBUG: Получены данные: {data}")
        
        # Проверяем
        if 'text' not in data:
            return jsonify({"error": "Нужно поле 'text'"}), 400
        if 'author_id' not in data:
            return jsonify({"error": "Нужно поле 'author_id'"}), 400
        
        # Просто возвращаем успех для теста
        return jsonify({
            "success": True,
            "message": "Комментарий принят",
            "task_id": task_id,
            "received": data
        }), 201
        
    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Удалить задачу"""
    try:
        import sqlite3
        conn = sqlite3.connect('task_manager.db')
        cursor = conn.cursor()
        
        # Проверяем существует ли задача
        cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Задача не найдена"}), 404
        
        # Удаляем
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        
        affected = cursor.rowcount
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Задача #{task_id} удалена",
            "deleted": affected
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    """Удалить комментарий"""
    try:
        import sqlite3
        conn = sqlite3.connect('task_manager.db')
        cursor = conn.cursor()
        
        # Проверяем существует ли комментарий
        cursor.execute("SELECT id FROM comments WHERE id = ?", (comment_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Комментарий не найден"}), 404
        
        # Удаляем
        cursor.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.commit()
        
        affected = cursor.rowcount
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Комментарий #{comment_id} удалён",
            "deleted": affected
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/comments/<int:comment_id>', methods=['PUT'])
def update_comment(comment_id):
    """Обновить комментарий"""
    data = request.get_json(silent=True) or {}

    text = data.get("text")
    if not text or not str(text).strip():
        return jsonify({"error": "Нужно непустое поле 'text'"}), 400

    text = str(text).strip()

    # Проверяем, что комментарий существует
    comment = database.get_comment_by_id(comment_id)
    if not comment:
        return jsonify({"error": "Комментарий не найден"}), 404

    # Обновляем
    success = database.update_comment(comment_id, text)
    if not success:
        return jsonify({"error": "Не удалось обновить комментарий"}), 400

    # Берём обновлённый комментарий
    updated = database.get_comment_by_id(comment_id)

    return jsonify({
        "success": True,
        "message": "Комментарий обновлён",
        "comment": updated
    }), 200

    

# ===== АУТЕНТИФИКАЦИЯ =====

@app.route('/auth/login', methods=['POST'])
def login():
    """Простая авторизация (заглушка)"""
    data = request.get_json(silent=True) or {}
    
    email = data.get('email', '')
    password = data.get('password', '')
    
    if email == 'admin@mail.ru' and password == '123456':
        return jsonify({
            "success": True,
            "message": "Авторизация успешна",
            "user": {
                "id": 1,
                "email": "admin@mail.ru",
                "username": "Администратор",
                "role": "admin"
            },
            "token": "fake-jwt-token-for-test"
        })
    else:
        return jsonify({
            "success": False,
            "error": "Неверный email или пароль"
        }), 401

@app.route('/users/me', methods=['GET'])
def get_current_user():
    """Профиль текущего пользователя"""
    return jsonify({
        "success": True,
        "user": {
            "id": 1,
            "email": "admin@mail.ru",
            "username": "Администратор",
            "role": "admin",
            "created_at": "2025-12-04 13:42:49"
        }
    })

@app.route('/users/me', methods=['PUT'])
def update_current_user():
    """Обновление профиля"""
    data = request.get_json(silent=True) or {}
    
    if 'username' not in data:
        return jsonify({"error": "Нужно поле 'username'"}), 400
    
    return jsonify({
        "success": True,
        "message": "Профиль обновлён",
        "updated": {
            "username": data['username']
        }
    })

# ===== ЗАПУСК СЕРВЕРА =====
if __name__ == '__main__':
    print("="*70)
    print("TASK MANAGER API")
    print("="*70)
    print("Сервер запущен: http://localhost:5000")
    print("\nДоступные endpoints:")
    print("\nПользователи:")
    print("  GET  /api/users          - все пользователи")
    print("  GET  /api/users/<id>     - пользователь по ID")
    print("\nЗадачи:")
    print("  GET  /api/tasks          - все задачи (с фильтрами)")
    print("  GET  /api/tasks/<id>     - задача по ID")
    print("  POST /api/tasks          - создать задачу (JSON в теле)")
    print("  PUT  /api/tasks/<id>     - обновить задачу")
    print("\nКомментарии:")
    print("  GET  /api/tasks/<id>/comments  - комментарии к задаче")
    print("  POST /api/tasks/<id>/comments  - добавить комментарий")
    print("\nПримеры фильтров для GET /api/tasks:")
    print("  ?status=в процессе&priority=высокий&page=1&limit=10")
    print("  ?author_id=2&executor_id=3&due_date_before=2024-12-10")
    print("="*70)
    
    app.run(debug=True, port=5000)
