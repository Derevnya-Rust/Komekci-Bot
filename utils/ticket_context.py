
import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TicketContext:
    """Контекст тикета заявки"""
    channel_id: int
    author_id: int
    steam_url: Optional[str] = None
    rust_hours: Optional[int] = None
    status: str = "pending"


# Простое хранилище контекстов в памяти
_contexts: Dict[int, TicketContext] = {}


def get_ctx(channel_id: int) -> Optional[TicketContext]:
    """Получить контекст тикета"""
    return _contexts.get(channel_id)


def set_ctx(channel_id: int, ctx: TicketContext):
    """Установить контекст тикета"""
    _contexts[channel_id] = ctx


def del_ctx(channel_id: int):
    """Удалить контекст тикета"""
    if channel_id in _contexts:
        del _contexts[channel_id]
