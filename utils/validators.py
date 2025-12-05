# utils/validators.py
import re
from datetime import datetime

# Допустимые значения из твоей БД (CHECK в таблице tasks)
ALLOWED_STATUSES = {
    'к выполнению',
    'в процессе',
    'выполнена',
    'отменена',
}

ALLOWED_PRIORITIES = {
    'низкий',
    'средний',
    'высокий',
}


def validate_email(email: str) -> list[str]:
    """Проверка email. Возвращает список ошибок (если пустой — всё ок)."""
    errors = []

    if not email:
        errors.append("Email обязателен")
        return errors

    email = email.strip()

    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(pattern, email):
        errors.append("Некорректный формат email")

    return errors


def validate_username(username: str) -> list[str]:
    """Проверка имени пользователя."""
    errors = []

    if not username:
        errors.append("Имя пользователя обязательно")
        return errors

    username = username.strip()

    if len(username) < 2:
        errors.append("Имя пользователя должно быть не короче 2 символов")
    if len(username) > 50:
        errors.append("Имя пользователя не должно быть длиннее 50 символов")

    return errors


def validate_task_data(data: dict, require_all: bool = False) -> list[str]:
    """
    Проверка данных задачи.
    require_all=True — для создания (обязательны title и author_id).
    """
    errors: list[str] = []

    # Заголовок
    title = data.get("title")
    if require_all:
        if not title or not str(title).strip():
            errors.append("Нужно непустое поле 'title'")
    if title:
        title = str(title).strip()
        if len(title) < 3:
            errors.append("Заголовок должен быть не короче 3 символов")
        if len(title) > 255:
            errors.append("Заголовок не должен быть длиннее 255 символов")

    # Автор (для создания задачи обязателен)
    author_id = data.get("author_id")
    if require_all and not author_id:
        errors.append("Нужно поле 'author_id' (ID автора)")

    # Статус
    status = data.get("status")
    if status is not None:
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"Недопустимый статус: {status}. "
                f"Разрешено: {', '.join(ALLOWED_STATUSES)}"
            )

    # Приоритет
    priority = data.get("priority")
    if priority is not None:
        if priority not in ALLOWED_PRIORITIES:
            errors.append(
                f"Недопустимый приоритет: {priority}. "
                f"Разрешено: {', '.join(ALLOWED_PRIORITIES)}"
            )

    # due_date — если есть, проверяем формат YYYY-MM-DD
    due_date = data.get("due_date")
    if due_date:
        try:
            datetime.strptime(str(due_date), "%Y-%m-%d")
        except ValueError:
            errors.append("Поле 'due_date' должно быть в формате YYYY-MM-DD")

    return errors
