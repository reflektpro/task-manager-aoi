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
    data = request.json
    
    if not data:
        return jsonify({"error": "Необходимы данные в формате JSON"}), 400
    
    # Валидация данных
    # Минимальная проверка
    if not data.get('title') or not data.get('author_id'):
        return jsonify({"error": "Нужны заголовок и ID автора"}), 400
    
    try:
        # Создаём задачу
        task_id = database.create_task(
            title=data['title'],
            description=data.get('description', ''),
            author_id=data['author_id'],
            executor_id=data.get('executor_id'),
            status=data.get('status', 'к выполнению'),
            priority=data.get('priority', 'средний'),
            due_date=data.get('due_date')
        )
        
        # Получаем созданную задачу
        task = database.get_task_by_id(task_id)
        
        return jsonify({
            "success": True,
            "message": "Задача создана",
            "task": task
        }), 201
        
    except Exception as e:
        return jsonify({"error": f"Ошибка при создании задачи: {str(e)}"}), 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """Обновить задачу"""
    data = request.json
    
    if not data:
        return jsonify({"error": "Необходимы данные для обновления"}), 400
    
    # Проверяем существует ли задача
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404
    
    # Валидация данных
    errors = validate_task_data(data, require_all=False)
    if errors:
        return jsonify({"error": "Ошибки валидации", "details": errors}), 400
    
    # Обновляем задачу
    success = database.update_task(task_id, **data)
    
    if not success:
        return jsonify({"error": "Не удалось обновить задачу"}), 400
    
    # Получаем обновлённую задачу
    updated_task = database.get_task_by_id(task_id)
    
    return jsonify({
        "success": True,
        "message": "Задача обновлена",
        "task": updated_task
    })

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
    """Добавить комментарий к задаче"""
    data = request.json
    
    if not data or 'text' not in data or 'author_id' not in data:
        return jsonify({"error": "Необходимы текст комментария и ID автора"}), 400
    
    # Проверяем существует ли задача
    task = database.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404
    
    # Проверяем текст комментария
    text = data['text'].strip()
    if not text or len(text) < 1:
        return jsonify({"error": "Текст комментария не может быть пустым"}), 400
    if len(text) > 1000:
        return jsonify({"error": "Текст комментария слишком длинный (макс. 1000 символов)"}), 400
    
    # Проверяем автора
    author_id = data['author_id']
    user = database.get_user_by_id(author_id)
    if not user:
        return jsonify({"error": "Автор не найден"}), 404
    
    # Добавляем комментарий
    try:
        comment_id = database.add_comment(task_id, author_id, text)
        
        # Получаем созданный комментарий
        comments = database.get_comments_by_task(task_id)
        new_comment = next((c for c in comments if c['id'] == comment_id), None)
        
        return jsonify({
            "success": True,
            "message": "Комментарий добавлен",
            "comment": new_comment
        }), 201
        
    except Exception as e:
        return jsonify({"error": f"Ошибка при добавлении комментария: {str(e)}"}), 500

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
