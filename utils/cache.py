
import asyncio
import time
import logging

logger = logging.getLogger(__name__)

_cache_data = {}
_cache_expiry = {}
_lock = asyncio.Lock()


class Cache:
    """Простой кэш с поддержкой dict-подобного доступа"""
    
    def __init__(self):
        self.data = _cache_data
        self.expiry = _cache_expiry
    
    def __getitem__(self, key):
        """Поддержка cache[key]"""
        result = asyncio.create_task(self.get(key))
        return result.result() if hasattr(result, 'result') else None
    
    def __setitem__(self, key, value):
        """Поддержка cache[key] = value"""
        asyncio.create_task(self.set(key, value))
    
    async def get(self, key, default=None):
        """Получить значение из кэша"""
        async with _lock:
            if key in self.data:
                # Проверяем срок действия
                if key in self.expiry and self.expiry[key] < time.time():
                    # Просрочено - удаляем
                    self.data.pop(key, None)
                    self.expiry.pop(key, None)
                    return default
                return self.data[key]
            return default
    
    async def set(self, key, value, ttl=300):
        """Сохранить значение в кэш"""
        async with _lock:
            self.data[key] = value
            self.expiry[key] = time.time() + ttl
    
    async def delete(self, key):
        """Удалить значение из кэша"""
        async with _lock:
            self.data.pop(key, None)
            self.expiry.pop(key, None)
    
    def clear(self):
        """Очистить весь кэш"""
        self.data.clear()
        self.expiry.clear()
        logger.info("🗑️ Кэш очищен")
    
    def info(self):
        """Информация о кэше"""
        # Подсчитываем только активные записи
        current_time = time.time()
        active_count = sum(1 for key in self.data if key not in self.expiry or self.expiry[key] >= current_time)
        logger.info(f"💾 Кэш: {active_count} записей")
        return active_count


# Глобальный экземпляр кэша
cache = Cache()


# Совместимость со старым API
async def get_cached(key, default=None):
    """Получить данные из кэша (старый API)"""
    return await cache.get(key, default)


async def set_cache(key, data, ttl=300):
    """Сохранить данные в кэш (старый API)"""
    await cache.set(key, data, ttl)


def clear_cache():
    """Очистить кэш (старый API)"""
    cache.clear()
