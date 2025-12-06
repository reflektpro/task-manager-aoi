# database.py
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import secrets
from werkzeug.security import generate_password_hash  # для тестовых пользователей

DATABASE = 'task_manager.db'

# ===== СОЗДАНИЕ ТАБЛИЦ =====
def init_db():
    """Создаёт все таблицы если их нет"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        username TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        role TEXT DEFAULT 'user' CHECK(role IN ('user', 'admin', 'super_admin'))
    )
    ''')
    
    # Таблица задач
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'к выполнению' 
            CHECK(status IN ('к выполнению', 'в процессе', 'выполнена', 'отменена')),
        priority TEXT DEFAULT 'средний' 
            CHECK(priority IN ('низкий', 'средний', 'высокий')),
        due_date TEXT,
        author_id INTEGER NOT NULL,
        executor_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (author_id) REFERENCES users(id),
        FOREIGN KEY (executor_id) REFERENCES users(id)
    )
    ''')
    
    # Таблица комментариев
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
        FOREIGN KEY (author_id) REFERENCES users(id)
    )
    ''')

    # Таблица токенов авторизации
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ База данных создана: {DATABASE}")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
@contextmanager
def get_db():
    """Контекстный менеджер для работы с БД"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Возвращает словари вместо кортежей
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()

def dict_from_row(row):
    """Преобразует sqlite3.Row в словарь"""
    return dict(row) if row else None

# ===== ФУНКЦИИ ДЛЯ USERS =====
def get_all_users():
    """Получить всех пользователей"""
    with get_db() as cursor:
        cursor.execute("SELECT id, email, username, created_at, role FROM users")
        return [dict_from_row(row) for row in cursor.fetchall()]

def get_user_by_id(user_id):
    """Получить пользователя по ID"""
    with get_db() as cursor:
        cursor.execute(
            "SELECT id, email, username, created_at, role FROM users WHERE id = ?",
            (user_id,)
        )
        return dict_from_row(cursor.fetchone())
    
def update_user_role(user_id, new_role):
    """Обновить роль пользователя."""
    if new_role not in ("user", "admin", "super_admin"):
        return False
    with get_db() as cursor:
        cursor.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (new_role, user_id)
        )
        return cursor.rowcount > 0

def get_user_usage_counts(user_id):
    """Вернуть количество задач и комментариев пользователя (для проверки перед удалением)."""
    with get_db() as cursor:
        # сколько задач он создавал/где был исполнителем
        cursor.execute(
            "SELECT COUNT(*) FROM tasks WHERE author_id = ? OR executor_id = ?",
            (user_id, user_id)
        )
        tasks_count = cursor.fetchone()[0]

        # сколько комментариев оставил
        cursor.execute(
            "SELECT COUNT(*) FROM comments WHERE author_id = ?",
            (user_id,)
        )
        comments_count = cursor.fetchone()[0]

        return {"tasks_count": tasks_count, "comments_count": comments_count}

def delete_user(user_id):
    """Удалить пользователя. ВАЖНО: перед этим нужно проверить, что у него нет задач/комментариев."""
    with get_db() as cursor:
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


def get_user_by_email(email):
    """Получить пользователя по email"""
    with get_db() as cursor:
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        return dict_from_row(cursor.fetchone())

def create_user(email, username, password_hash, role='user'):
    """Создать нового пользователя"""
    with get_db() as cursor:
        try:
            cursor.execute(
                """INSERT INTO users (email, username, password_hash, role) 
                   VALUES (?, ?, ?, ?)""",
                (email, username, password_hash, role)
            )
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

def get_user_by_access_token(token: str):
    """
    Вернуть пользователя по access-токену из таблицы auth_tokens.
    """
    with get_db() as cursor:
        cursor.execute('''
            SELECT 
                u.id,
                u.email,
                u.username,
                u.created_at,
                u.role,
                t.expires_at
            FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token = ?
        ''', (token,))
        row = cursor.fetchone()
        if not row:
            return None

        data = dict_from_row(row)

        # проверка срока действия токена
        expires_at = data.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) <= datetime.utcnow():
                    return None
            except Exception:
                # если формат неожиданно странный — не роняем сервер
                pass

        # нам от токена нужен только пользователь
        return {
            "id": data["id"],
            "email": data["email"],
            "username": data["username"],
            "created_at": data["created_at"],
            "role": data["role"],
        }



# ===== ФУНКЦИИ ДЛЯ TASKS =====
def get_all_tasks(filters=None, limit=100, offset=0):
    """Получить все задачи с фильтрами"""
    with get_db() as cursor:
        query = '''
        SELECT 
            t.id, t.title, t.description, t.status, t.priority, t.due_date,
            t.author_id, t.executor_id, t.created_at, t.updated_at,
            u1.username as author_name,
            u2.username as executor_name
        FROM tasks t
        LEFT JOIN users u1 ON t.author_id = u1.id
        LEFT JOIN users u2 ON t.executor_id = u2.id
        WHERE 1=1
        '''
        params = []
        
        if filters:
            # Фильтр по статусу
            if 'status' in filters:
                query += " AND t.status = ?"
                params.append(filters['status'])
            
            # Фильтр по приоритету
            if 'priority' in filters:
                query += " AND t.priority = ?"
                params.append(filters['priority'])
            
            # Фильтр по автору
            if 'author_id' in filters:
                query += " AND t.author_id = ?"
                params.append(filters['author_id'])
            
            # Фильтр по исполнителю
            if 'executor_id' in filters:
                query += " AND t.executor_id = ?"
                params.append(filters['executor_id'])
            
            # Фильтр по сроку выполнения
            if 'due_date_before' in filters:
                query += " AND t.due_date <= ?"
                params.append(filters['due_date_before'])
            
            if 'due_date_after' in filters:
                query += " AND t.due_date >= ?"
                params.append(filters['due_date_after'])
        
        query += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        return [dict_from_row(row) for row in cursor.fetchall()]

def get_task_by_id(task_id):
    """Получить задачу по ID"""
    with get_db() as cursor:
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
        return dict_from_row(cursor.fetchone())

def create_task(title, description, author_id, executor_id=None, 
                status='к выполнению', priority='средний', due_date=None):
    """Создать новую задачу"""
    with get_db() as cursor:
        cursor.execute('''
        INSERT INTO tasks 
        (title, description, status, priority, due_date, author_id, executor_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, description, status, priority, due_date, author_id, executor_id))
        return cursor.lastrowid

def update_task(task_id, **kwargs):
    """Обновить задачу"""
    if not kwargs:
        return False
    
    allowed_fields = ['title', 'description', 'status', 'priority', 'due_date', 'executor_id']
    updates = []
    params = []
    
    for field, value in kwargs.items():
        if field in allowed_fields and value is not None:
            updates.append(f"{field} = ?")
            params.append(value)
    
    if not updates:
        return False
    
    params.append(task_id)
    
    with get_db() as cursor:
        cursor.execute(
            f"UPDATE tasks SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params
        )
        return cursor.rowcount > 0

def delete_task(task_id):
    """Удалить задачу"""
    with get_db() as cursor:
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

# ===== ФУНКЦИИ ДЛЯ COMMENTS =====
def get_comments_by_task(task_id):
    """Получить комментарии к задаче"""
    with get_db() as cursor:
        cursor.execute('''
        SELECT c.*, u.username as author_name
        FROM comments c
        JOIN users u ON c.author_id = u.id
        WHERE c.task_id = ?
        ORDER BY c.created_at
        ''', (task_id,))
        return [dict_from_row(row) for row in cursor.fetchall()]

def add_comment(task_id, author_id, text):
    """Добавить комментарий к задаче"""
    with get_db() as cursor:
        cursor.execute(
            "INSERT INTO comments (task_id, author_id, text) VALUES (?, ?, ?)",
            (task_id, author_id, text)
        )
        return cursor.lastrowid
    
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


def update_comment(comment_id, text):
    """Обновить текст комментария"""
    if not text:
        return False

    with get_db() as cursor:
        cursor.execute(
            "UPDATE comments SET text = ? WHERE id = ?",
            (text, comment_id)
        )
        return cursor.rowcount > 0
    
def get_task_stats():
    """Получить статистику задач по статусам и приоритетам."""
    with get_db() as cursor:
        stats = {
            "by_status": {},
            "by_priority": {},
        }

        cursor.execute("SELECT status, COUNT(*) as count FROM tasks GROUP BY status")
        for row in cursor.fetchall():
            stats["by_status"][row["status"]] = row["count"]

        cursor.execute("SELECT priority, COUNT(*) as count FROM tasks GROUP BY priority")
        for row in cursor.fetchall():
            stats["by_priority"][row["priority"]] = row["count"]

        return stats


def get_active_users(limit: int = 10):
    """Получить список активных пользователей (по задачам и комментариям)."""
    with get_db() as cursor:
        cursor.execute("""
        SELECT 
            u.id,
            u.email,
            u.username,
            u.role,
            u.created_at,
            COUNT(DISTINCT t.id) AS tasks_count,
            COUNT(DISTINCT c.id) AS comments_count
        FROM users u
        LEFT JOIN tasks t ON t.author_id = u.id
        LEFT JOIN comments c ON c.author_id = u.id
        GROUP BY u.id, u.email, u.username, u.role, u.created_at
        ORDER BY tasks_count + comments_count DESC, u.id
        LIMIT ?
        """, (limit,))
        return [dict_from_row(row) for row in cursor.fetchall()]




# ===== ИНИЦИАЛИЗАЦИЯ =====
def add_test_data():
    """Добавить тестовые данные"""
    with get_db() as cursor:
        # Проверяем, есть ли уже данные
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] > 0:
            print("✅ Тестовые данные уже существуют")
            return
        
        # Тестовые пользователи (пароль: 123456)
        users = [
            ('super@mail.ru', 'Супер Админ', 'super_admin'),
            ('admin@mail.ru', 'Администратор', 'admin'),
            ('ivan@mail.ru', 'Иван Петров', 'user'),
            ('anna@mail.ru', 'Анна Сидорова', 'user')
        ]
        
        for email, username, role in users:
            cursor.execute(
                """INSERT INTO users (email, username, password_hash, role) 
                   VALUES (?, ?, ?, ?)""",
                (email, username, generate_password_hash("123456"), role)
            )


        
        # Тестовые задачи
        tasks = [
            ('Настроить сервер', 'Установить и настроить веб-сервер', 2, 3, 'в процессе', 'высокий', '2024-12-10'),
            ('Создать API', 'Написать REST API endpoints', 1, 4, 'к выполнению', 'средний', '2024-12-15'),
            ('Тестирование', 'Протестировать функционал', 2, 3, 'к выполнению', 'низкий', None),
        ]
        
        for title, desc, author, executor, status, priority, due_date in tasks:
            cursor.execute('''
            INSERT INTO tasks 
            (title, description, author_id, executor_id, status, priority, due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (title, desc, author, executor, status, priority, due_date))
        
        # Тестовые комментарии
        comments = [
            (1, 1, 'Сервер нужно настроить до конца недели'),
            (1, 3, 'Какая версия Ubuntu ставим?'),
            (2, 1, 'API должно быть RESTful'),
        ]
        
        for task_id, author_id, text in comments:
            cursor.execute(
                "INSERT INTO comments (task_id, author_id, text) VALUES (?, ?, ?)",
                (task_id, author_id, text)
            )
        
        print("✅ Тестовые данные добавлены")

# ===== ФУНКЦИИ ДЛЯ ТОКЕНОВ АВТОРИЗАЦИИ =====

def create_token(user_id: int, expires_in: int = 3600) -> str:
    """Создать новый токен авторизации для пользователя."""
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as cursor:
        cursor.execute(
            "INSERT INTO auth_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at)
        )

    return token


def get_user_by_token(token: str):
    """Получить пользователя по токену, если токен ещё не истёк."""
    with get_db() as cursor:
        cursor.execute('''
        SELECT 
            u.id, u.email, u.username, u.created_at, u.role
        FROM auth_tokens t
        JOIN users u ON t.user_id = u.id
        WHERE t.token = ?
          AND t.expires_at > CURRENT_TIMESTAMP
        ''', (token,))
        row = cursor.fetchone()
        return dict_from_row(row)


def refresh_token(old_token: str, expires_in: int = 3600):
    """Обновить токен: старый инвалидируем, создаём новый."""
    with get_db() as cursor:
        cursor.execute('''
        SELECT user_id FROM auth_tokens
        WHERE token = ? AND expires_at > CURRENT_TIMESTAMP
        ''', (old_token,))
        row = cursor.fetchone()
        if not row:
            return None

        user_id = row["user_id"]

        # Удаляем старый токен
        cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (old_token,))

        # Создаём новый
        new_token = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO auth_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (new_token, user_id, expires_at)
        )

        return new_token


# При импорте инициализируем БД
init_db()
add_test_data()
