# cache.py
import time
from typing import Any, Dict, Optional, Tuple

# Кэш списка задач (одна "выборка" по ключу)
TASK_LIST_CACHE: Dict[str, Any] = {
    "key": None,
    "data": None,        # сюда кладём словарь вида {"count": int, "tasks": [...]}
    "expires_at": 0.0,
}

# Кэш деталей задач: task_id -> {"data": {...}, "expires_at": ts}
TASK_DETAIL_CACHE: Dict[int, Dict[str, Any]] = {}

# TTL в секундах (5 минут)
TASK_CACHE_TTL = 300


def _now() -> float:
    return time.time()


def make_task_list_cache_key(filters: Dict[str, Any], page: int, limit: int) -> str:
    """Делаем детерминированный ключ для кэша списка задач."""
    # Сортируем фильтры, чтобы при одинаковых параметрах ключ был тем же
    items = sorted(filters.items())
    return f"{items}|page={page}|limit={limit}"


def get_cached_task_list(key: str) -> Optional[Dict[str, Any]]:
    """Вернуть кэшированный список задач или None, если нет/протух."""
    if TASK_LIST_CACHE["key"] != key:
        return None

    if TASK_LIST_CACHE["expires_at"] < _now():
        # протух — чистим
        TASK_LIST_CACHE["key"] = None
        TASK_LIST_CACHE["data"] = None
        TASK_LIST_CACHE["expires_at"] = 0.0
        return None

    return TASK_LIST_CACHE["data"]


def set_cached_task_list(key: str, data: Dict[str, Any]) -> None:
    """Положить список задач в кэш."""
    TASK_LIST_CACHE["key"] = key
    TASK_LIST_CACHE["data"] = data
    TASK_LIST_CACHE["expires_at"] = _now() + TASK_CACHE_TTL


def invalidate_task_list_cache() -> None:
    """Полностью сбросить кэш списка задач."""
    TASK_LIST_CACHE["key"] = None
    TASK_LIST_CACHE["data"] = None
    TASK_LIST_CACHE["expires_at"] = 0.0


def get_cached_task_detail(task_id: int) -> Optional[Dict[str, Any]]:
    """Вернуть кэшированные детали задачи или None."""
    entry = TASK_DETAIL_CACHE.get(task_id)
    if not entry:
        return None

    if entry["expires_at"] < _now():
        TASK_DETAIL_CACHE.pop(task_id, None)
        return None

    return entry["data"]


def set_cached_task_detail(task_id: int, data: Dict[str, Any]) -> None:
    """Положить детали задачи в кэш."""
    TASK_DETAIL_CACHE[task_id] = {
        "data": data,
        "expires_at": _now() + TASK_CACHE_TTL,
    }


def invalidate_task_detail(task_id: int) -> None:
    """Сбросить кэш конкретной задачи."""
    TASK_DETAIL_CACHE.pop(task_id, None)


def invalidate_all_task_details() -> None:
    """Сбросить кэш всех задач (на всякий случай, если пригодится)."""
    TASK_DETAIL_CACHE.clear()
