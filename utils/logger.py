from __future__ import annotations
import logging
import os
import sys
from config import config
from datetime import datetime
from typing import Optional
import asyncio

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%d.%m.%Y %H:%M:%S"

# Глобальный счётчик ошибок
_error_count = 0


def init_logging():
    """Инициализация оптимизированного логирования для Replit"""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    level_num = getattr(logging, level, logging.INFO)

    root = logging.getLogger()
    # чистим хендлеры, чтобы не было дублей при перезапусках
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    root.addHandler(handler)
    root.setLevel(level_num)

    # умерить болтливость сторонних логгеров
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # добавляем счётчик ошибок
    error_counter = ErrorCountingHandler()
    root.addHandler(error_counter)

    logging.info(f"Логирование инициализировано: уровень={logging.getLevelName(level_num)}")
    return None


class ErrorCountingHandler(logging.Handler):
    """Handler для подсчёта ошибок во время запуска"""

    def emit(self, record):
        global _error_count
        if record.levelno >= logging.ERROR:
            _error_count += 1


def get_error_count():
    """Возвращает количество ошибок с момента инициализации логирования"""
    return _error_count


def setup_basic_logger():
    """Настройка базового логгера - оставляем для совместимости"""
    logging.basicConfig(
        level=logging.INFO,
        format="🤖 %(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(__name__)


def setup_logger(bot=None):
    """Настройка логирования с поддержкой Discord - оставляем для совместимости"""
    root_logger = logging.getLogger()
    return root_logger


def get_module_logger(module_name: str):
    """
    Получает logger для модуля с настроенными handler'ами.
    Логгеры модулей не имеют собственных handler'ов и передают всё в root logger.
    """
    module_logger = logging.getLogger(module_name)
    module_logger.propagate = True  # Включаем всплытие для централизованного логирования
    return module_logger


async def log_technical_error(channel, error_type, message, traceback):
    """Логирование технических ошибок"""
    logger = logging.getLogger("technical_errors")
    logger.error(f"[{error_type}] {message}")
    if traceback:
        logger.debug(f"Traceback: {traceback}")