# database.py
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import secrets
from werkzeug.security import generate_password_hash # для тестовых пользователей
from typing import List, Optional, Dict, Any  
TOKEN_TTL_MINUTES = 120
DB_NAME = 'task_manager.db'

# ===== СОЗДАНИЕ ТАБЛИЦ =====
def init_db():
    """Создаёт все таблицы если их нет"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        username TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT (DATETIME('now','localtime')),
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
        created_at TEXT DEFAULT (DATETIME('now','localtime')),
        updated_at TEXT DEFAULT (DATETIME('now','localtime')),
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
        created_at TEXT DEFAULT (DATETIME('now','localtime')),
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
        created_at TEXT DEFAULT (DATETIME('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            content_type TEXT,
            size_bytes INTEGER,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            uploader_id INTEGER,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE SET NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ База данных создана: {DB_NAME}")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
@contextmanager
def get_db():
    """Контекстный менеджер для работы с БД"""
    conn = sqlite3.connect(DB_NAME)
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

def get_user_by_access_token(token):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT u.*, a.expires_at
            FROM auth_tokens a
            JOIN users u ON a.user_id = u.id
            WHERE a.token = ?
            """,
            (token,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        if _now_utc() > expires_at:
            # токен истёк — удаляем и считаем недействительным
            cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
            return None

        return dict_from_row(row)


def delete_access_token(token: str) -> bool:
    """Удаляет конкретный токен."""
    with get_db() as cursor:
        cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        return cursor.rowcount > 0


def delete_all_tokens_for_user(user_id: int) -> int:
    """На всякий случай: удалить все токены пользователя (массовый логаут)."""
    with get_db() as cursor:
        cursor.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        return cursor.rowcount

def update_user_basic(user_id, fields: dict):
    if not fields:
        return get_user_by_id(user_id)

    sets = []
    params = []
    for key, val in fields.items():
        sets.append(f"{key} = ?")
        params.append(val)

    params.append(user_id)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE users
            SET {", ".join(sets)}
            WHERE id = ?
        """, params)
        conn.commit()
    return get_user_by_id(user_id)


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
            f"UPDATE tasks SET {', '.join(updates)}, "
            "updated_at = DATETIME('now','localtime') "
            "WHERE id = ?",
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

# ===== ФУНКЦИИ ДЛЯ ATTACHMENT ========
def create_attachment(task_id, uploader_id, filename_orig,
                      filename_stored, mime_type=None, size_bytes=None):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO attachments (
            task_id, uploader_id, filename_orig,
            filename_stored, mime_type, size_bytes
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (task_id, uploader_id, filename_orig,
          filename_stored, mime_type, size_bytes))

    attachment_id = cursor.lastrowid
    conn.commit()

    cursor.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return dict(row)

def get_attachments_for_task(task_id: int) -> list[dict]:
    """
    Все файлы, прикреплённые к задаче.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            task_id,
            stored_name,
            original_name,
            content_type,
            size_bytes,
            uploaded_by,
            uploaded_at
        FROM task_files
        WHERE task_id = ?
        ORDER BY id DESC
        """,
        (task_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_attachment_by_id(attachment_id: int) -> dict | None:
    """
    Один файл по ID.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            task_id,
            stored_name,
            original_name,
            content_type,
            size_bytes,
            uploaded_by,
            uploaded_at
        FROM task_files
        WHERE id = ?
        """,
        (attachment_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_attachment(attachment_id: int) -> bool:
    """
    Удалить запись о файле (сам файл на диске удаляется в app.py).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM task_files WHERE id = ?", (attachment_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted > 0


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
def _now_utc():
    return datetime.utcnow()

def create_auth_token(user_id):
    token = secrets.token_urlsafe(32)
    now = _now_utc()
    expires_at = now + timedelta(minutes=TOKEN_TTL_MINUTES)

    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO auth_tokens (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                token,
                user_id,
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                now.strftime("%Y-%m-%d %H:%M:%S"),
            ),
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
    
# ====== ФАЙЛЫ ===========
def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def save_task_file(task_id: int,
                   stored_name: str,
                   original_name: str,
                   content_type: str | None,
                   size_bytes: int,
                   uploaded_by: int | None = None) -> dict | None:
    """
    Сохранить информацию о файле задачи в таблице task_files.
    Возвращает dict с полями файла.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO task_files (
            task_id,
            stored_name,
            original_name,
            content_type,
            size_bytes,
            uploaded_by
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, stored_name, original_name, content_type, size_bytes, uploaded_by),
    )
    attachment_id = cur.lastrowid
    conn.commit()

    cur.execute(
        """
        SELECT
            id,
            task_id,
            stored_name,
            original_name,
            content_type,
            size_bytes,
            uploaded_by,
            uploaded_at
        FROM task_files
        WHERE id = ?
        """,
        (attachment_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_task_files_for_task(task_id: int) -> list[dict]:
    """
    Список файлов, прикреплённых к конкретной задаче.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT
            tf.id,
            tf.task_id,
            tf.original_name,
            tf.stored_name,
            tf.content_type,
            tf.size_bytes,
            tf.uploaded_at,
            tf.uploader_id,
            u.username AS uploader_name
        FROM task_files tf
        LEFT JOIN users u ON tf.uploader_id = u.id
        WHERE tf.task_id = ?
        ORDER BY tf.uploaded_at DESC, tf.id DESC
        ''',
        (task_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task_file(file_id: int) -> Optional[dict]:
    """
    Получить один файл по id.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT
            tf.id,
            tf.task_id,
            tf.original_name,
            tf.stored_name,
            tf.content_type,
            tf.size_bytes,
            tf.uploaded_at,
            tf.uploader_id,
            u.username AS uploader_name
        FROM task_files tf
        LEFT JOIN users u ON tf.uploader_id = u.id
        WHERE tf.id = ?
        ''',
        (file_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_task_file(file_id: int) -> bool:
    """
    Удалить запись о файле. Возвращает True, если что-то было удалено.
    (сам физический файл должен удаляться во Flask-обработчике)
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM task_files WHERE id = ?', (file_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


# Алиасы на всякий случай, если во view мы используем другие имена
def get_task_files(task_id: int) -> list[dict]:
    """Алиас для get_task_files_for_task."""
    return get_task_files_for_task(task_id)


def get_task_file_by_id(file_id: int) -> Optional[dict]:
    """Алиас для get_task_file."""
    return get_task_file(file_id)


# При импорте инициализируем БД
init_db()
add_test_data()
