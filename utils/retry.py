import asyncio
import logging
from functools import wraps
from typing import Callable, Any, Tuple

logger = logging.getLogger(__name__)


class RetryError(Exception):
    """Исключение для ошибок повторных попыток"""
    pass


def retry_async(max_attempts: int = 3, delays: Tuple[float, ...] = (1, 2, 4)):
    """Декоратор для повторных попыток асинхронных функций"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except RetryError as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = delays[min(attempt, len(delays) - 1)]
                        logger.debug(f"Повтор {attempt + 1}/{max_attempts} через {delay}с: {e}")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Все попытки исчерпаны для {func.__name__}: {e}")
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = delays[min(attempt, len(delays) - 1)]
                        logger.debug(f"Повтор {attempt + 1}/{max_attempts} через {delay}с: {e}")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Все попытки исчерпаны для {func.__name__}: {e}")

            raise last_exception

        return wrapper
    return decorator