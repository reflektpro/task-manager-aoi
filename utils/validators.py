# utils/validators.py
import re
from datetime import datetime

def validate_email(email):
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email)) if email else False

def validate_username(username):
    if not username or len(username.strip()) < 2:
        return False
    if len(username) > 50:
        return False
    return True

def validate_task_data(data, require_all=False):
    errors = []
    if require_all:
        if "title" not in data or "author_id" not in data:
            errors.append("ужны title и author_id")
    return errors