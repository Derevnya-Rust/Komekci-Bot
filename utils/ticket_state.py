import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Простое хранилище состояния тикетов в памяти
_ticket_owners: Dict[int, int] = {}  # channel_id -> user_id


def get_ticket_owner(channel_id: int) -> Optional[int]:
    """Получить владельца тикета"""
    return _ticket_owners.get(channel_id)


def set_ticket_owner(channel_id: int, user_id: int):
    """Установить владельца тикета"""
    _ticket_owners[channel_id] = user_id
    logger.debug(f"Установлен владелец тикета {channel_id}: {user_id}")


def del_ticket_owner(channel_id: int):
    """Удалить владельца тикета"""
    if channel_id in _ticket_owners:
        del _ticket_owners[channel_id]
        logger.debug(f"Удален владелец тикета {channel_id}")