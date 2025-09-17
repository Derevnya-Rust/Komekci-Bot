import os
import aiohttp
import datetime
import asyncio
import time
import re
from typing import Dict, Optional, List
import logging
from utils.logger import get_module_logger

from utils.retry import retry_async, RetryError
from utils.cache import get_cached, set_cache
from config import config
from utils.discord_logger import log_to_channel, log_error, discord_logger

logger = get_module_logger(__name__)

async def get_steamid64_from_url(steam_url: str) -> Optional[str]:
    """
    Конвертирует Steam URL в SteamID64
    Если ссылка в формате /id/username, использует ResolveVanityURL
    Если уже steamid64, возвращает напрямую
    """
    try:
        if not steam_url or "steamcommunity.com" not in steam_url:
            return None
        
        # Извлекаем ID из URL
        from handlers.novichok import extract_steam_id_from_url
        steam_id = extract_steam_id_from_url(steam_url)
        
        if not steam_id:
            return None
        
        # Если это уже SteamID64 (только цифры и длина ~17)
        if steam_id.isdigit() and len(steam_id) >= 17:
            return steam_id
        
        # Если это vanity URL, используем ResolveVanityURL
        vanity_data = await steam_client.resolve_vanity_url(steam_id)
        if vanity_data and vanity_data.get("success") == 1:
            return vanity_data.get("steamid")
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Ошибка конвертации Steam URL: {e}")
        return None

# Псевдоним для обратной совместимости
async def get_steam_id64(steam_url: str) -> Optional[str]:
    """Псевдоним для get_steamid64_from_url"""
    return await get_steamid64_from_url(steam_url)





async def get_steamid64_from_url(steam_url: str) -> Optional[str]:
    """
    Универсальная функция для получения steamID64 из любого Steam URL.
    Поддерживает как vanity URL, так и прямые ссылки на профили.
    """
    if not steam_url or "steamcommunity.com" not in steam_url.lower():
        logger.error(f"❌ Неверный Steam URL: {steam_url}")
        return None

    # Извлекаем ID из URL
    if "/profiles/" in steam_url:
        # Прямая ссылка на профиль с steamID64
        match = re.search(r"/profiles/(\d+)", steam_url)
        if match:
            steam_id = match.group(1)
            # Проверяем, что это валидный steamID64
            if len(steam_id) == 17 and steam_id.startswith("765611"):
                logger.info(f"✅ Найден валидный SteamID64: {steam_id}")
                return steam_id
            else:
                logger.warning(f"⚠️ Подозрительный SteamID64: {steam_id}")
                return steam_id  # Возвращаем как есть, пусть API проверит
    elif "/id/" in steam_url:
        # Vanity URL, нужно преобразовать
        match = re.search(r"/id/([^/]+)", steam_url)
        if match:
            vanity_name = match.group(1)
            logger.info(f"🔄 Преобразуем vanity URL: {vanity_name}")
            resolved_id = await resolve_vanity_url(vanity_name)
            if resolved_id:
                logger.info(
                    f"✅ Vanity URL '{vanity_name}' преобразован в SteamID64: {resolved_id}"
                )
                return resolved_id
            else:
                logger.error(f"❌ Не удалось преобразовать vanity URL: {vanity_name}")
                return None

    logger.error(f"❌ Не удалось извлечь ID из Steam URL: {steam_url}")
    return None


@retry_async(max_attempts=3, delays=(2, 4, 8))
async def resolve_vanity_url(vanity: str) -> Optional[str]:
    """Получает настоящий SteamID64 по кастомному Vanity URL"""
    api_key = os.getenv("STEAM_API_KEY")

    if not api_key:
        logger.error("STEAM_API_KEY не установлен в переменных окружения")
        return None

    url = f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key={api_key}&vanityurl={vanity}"

    try:
        # Добавляем задержку для предотвращения лимитов
        await asyncio.sleep(1.5)

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("response", {}).get("success") == 1:
                        steamid = data["response"].get("steamid")
                        logger.info(
                            f"✅ Vanity URL '{vanity}' преобразован в SteamID: {steamid}"
                        )
                        return steamid
                    else:
                        logger.warning(f"⚠️ Vanity URL '{vanity}' не найден в Steam")
                        return None
                elif response.status == 429:
                    logger.warning(
                        f"Steam API: лимит превышен (429) для Vanity URL '{vanity}'"
                    )
                    await asyncio.sleep(90)
                    raise RetryError("Rate limit exceeded")
                else:
                    logger.error(
                        f"Steam API вернул статус {response.status} для Vanity URL '{vanity}'"
                    )
                    return None

    except asyncio.TimeoutError:
        logger.error(f"Таймаут запроса Vanity URL '{vanity}'")
        raise RetryError("Request timeout")
    except aiohttp.ClientError as e:
        logger.warning(f"Сетевая ошибка при запросе Vanity URL '{vanity}': {e}")
        raise  # Позволяем retry декоратору обработать
    except ValueError as e:
        logger.error(f"Ошибка парсинга JSON для Vanity URL '{vanity}': {e}")
        return None
    except RetryError:
        raise  # Проброс для retry декоратора
    except Exception as e:
        logger.warning(f"Неожиданная ошибка при запросе Vanity URL '{vanity}': {e}")
        raise  # Позволяем retry декоратору обработать


class SteamAPIClient:
    """Клиент для работы с Steam API с retry логикой и кэшированием"""

    def __init__(self):
        self.api_key = config.STEAM_API_KEY
        self._request_times: List[float] = []  # для rate limiting

        if not self.api_key:
            logger.warning("STEAM_API_KEY не установлен в конфигурации")

    async def _enforce_rate_limit(self):
        """Обеспечивает rate limiting: не более 1 запроса в секунду и 100 за 5 минут"""
        now = time.time()

        # Убираем старые запросы (старше 5 минут)
        self._request_times = [t for t in self._request_times if now - t < 300]

        # Проверяем лимит 100 запросов за 5 минут
        if len(self._request_times) >= 90:  # Снижен лимит для безопасности
            sleep_time = 300 - (now - self._request_times[0]) + 10  # +10с запас
            if sleep_time > 0:
                logger.warning(
                    f"Steam API: приближение к лимиту 100 запросов, ждем {sleep_time:.1f}с"
                )
                await asyncio.sleep(sleep_time)
                # Очищаем список после ожидания
                self._request_times = [
                    t for t in self._request_times if now + sleep_time - t < 300
                ]

        # Проверяем лимит 1 запрос в секунду (увеличен интервал для безопасности)
        if self._request_times and now - self._request_times[-1] < 1.2:
            sleep_time = 1.2 - (now - self._request_times[-1])
            logger.debug(f"Steam API: rate limiting, ждем {sleep_time:.2f}с")
            await asyncio.sleep(sleep_time)

        # Записываем время запроса
        self._request_times.append(time.time())

    @retry_async(max_attempts=3, delays=(2, 4, 8))
    async def _request(self, endpoint_url: str) -> Optional[dict]:
        """Единая функция для запросов к Steam API с retry и кэшированием"""
        # Проверяем кэш
        cached_data = await get_cached(endpoint_url)
        if cached_data is not None:
            logger.debug(f"Используем кэш для {endpoint_url}")
            return cached_data

        # Применяем rate limiting
        await self._enforce_rate_limit()

        # Дополнительная защитная задержка
        await asyncio.sleep(1.5)

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(endpoint_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Кэшируем только успешные ответы
                        await set_cache(endpoint_url, data, ttl=10)
                        return data
                    elif resp.status in (401, 403):
                        logger.error("Steam API key invalid or access denied")
                        # Возвращаем специальный маркер для обработки
                        return {
                            "steam_api_error": True,
                            "error_type": "auth_error",
                        }  # НЕ кэшируем ошибки
                    elif resp.status == 429:
                        # Скрываем от игроков, логируем в технические логи
                        from utils.logger import log_technical_error
                        import traceback

                        asyncio.create_task(
                            log_technical_error(
                                None,
                                "steam_api",
                                f"Steam API rate limit exceeded (429) для {endpoint_url}",
                                traceback.format_exc(),
                            )
                        )
                        await asyncio.sleep(90)
                        raise RetryError("Rate limit exceeded")
                    elif resp.status in (400, 500, 502, 503):
                        from utils.logger import log_technical_error
                        import traceback

                        asyncio.create_task(
                            log_technical_error(
                                None,
                                "steam_api",
                                f"Steam API server error {resp.status} для {endpoint_url}",
                                traceback.format_exc(),
                            )
                        )
                        raise RetryError(f"Server error {resp.status}")
                    else:
                        from utils.logger import log_technical_error
                        import traceback

                        asyncio.create_task(
                            log_technical_error(
                                None,
                                "steam_api",
                                f"Steam API неожиданный статус {resp.status} для {endpoint_url}",
                                traceback.format_exc(),
                            )
                        )
                        return None
            except asyncio.TimeoutError:
                from utils.logger import log_technical_error
                import traceback

                asyncio.create_task(
                    log_technical_error(
                        None,
                        "steam_api",
                        f"Steam API timeout для {endpoint_url}",
                        traceback.format_exc(),
                    )
                )
                raise RetryError("Request timeout")
            except aiohttp.ClientError as e:
                from utils.logger import log_technical_error
                import traceback

                asyncio.create_task(
                    log_technical_error(
                        None,
                        "steam_api",
                        f"Steam API ClientError: {str(e)} для {endpoint_url}",
                        traceback.format_exc(),
                    )
                )
                raise  # Позволяем retry декоратору обработать

    async def _get_player_profile_data(self, steam_id: str) -> dict:
        """Получить детальные данные профиля включая никнейм"""
        # Проверяем, является ли steam_id числом
        if not steam_id.isdigit():
            logger.info(
                f"🔄 Vanity URL обнаружен в _get_player_profile_data: {steam_id}, преобразуем в SteamID64..."
            )
            resolved_id = await resolve_vanity_url(steam_id)
            if not resolved_id:
                logger.error(
                    f"❌ Не удалось преобразовать vanity URL '{steam_id}' в SteamID64"
                )
                return {}
            steam_id = resolved_id
            logger.info(f"✅ Vanity URL преобразован в SteamID64: {steam_id}")

        try:
            url = (
                f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
                f"?key={self.api_key}&steamids={steam_id}"
            )

            data = await self._request(url)

            if not data or not data.get("response", {}).get("players"):
                return {}

            player = data["response"]["players"][0]
            
            return {
                "steamid": player.get("steamid"),
                "personaname": player.get("personaname", ""),
                "profileurl": player.get("profileurl", ""),
                "avatar": player.get("avatar", ""),
                "avatarmedium": player.get("avatarmedium", ""),
                "avatarfull": player.get("avatarfull", ""),
                "communityvisibilitystate": player.get("communityvisibilitystate", 1),
                "profilestate": player.get("profilestate", 0),
                "lastlogoff": player.get("lastlogoff"),
                "timecreated": player.get("timecreated"),
            }

        except Exception as e:
            logger.error(f"❌ Ошибка получения данных профиля для {steam_id}: {e}")
            return {}

    async def get_player_summary(self, steam_id: str) -> dict:
        """Получить основную информацию об игроке"""
        # Проверяем, является ли steam_id числом
        if not steam_id.isdigit():
            logger.info(
                f"🔄 Vanity URL обнаружен в get_player_summary: {steam_id}, преобразуем в SteamID64..."
            )
            resolved_id = await resolve_vanity_url(steam_id)
            if not resolved_id:
                logger.error(
                    f"❌ Не удалось преобразовать vanity URL '{steam_id}' в SteamID64"
                )
                return {
                    "success": False,
                    "steamid": None,
                    "personaname": None,
                    "error_message": f"Не удалось преобразовать vanity URL '{steam_id}' в SteamID64",
                }
            steam_id = resolved_id
            logger.info(f"✅ Vanity URL преобразован в SteamID64: {steam_id}")

        try:
            await log_to_channel(
                "API", f"Запрос GetPlayerSummaries для SteamID: {steam_id}"
            )

            url = (
                f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
                f"?key={self.api_key}&steamids={steam_id}"
            )

            data = await self._request(url)

            result = {
                "success": False,
                "steamid": None,
                "personaname": None,
                "error_message": "",
            }

            if not data:
                result["error_message"] = "Не удалось получить данные профиля"
                await log_to_channel(
                    "API",
                    f"Ошибка GetPlayerSummaries для SteamID: {steam_id}. Не удалось получить данные профиля.",
                )
                return result

            # Проверяем на ошибки API
            if isinstance(data, dict) and data.get("steam_api_error"):
                result["error_message"] = "Steam API недоступен или неверный ключ"
                await log_to_channel(
                    "API",
                    f"Ошибка GetPlayerSummaries для SteamID: {steam_id}. Ошибка Steam API.",
                )
                return result

            # Обработка успешного ответа
            if data.get("response", {}).get("players"):
                player = data["response"]["players"][0]
                result["success"] = True
                result["steamid"] = player.get("steamid")
                result["personaname"] = player.get("personaname", "")
            else:
                result["error_message"] = "Профиль не найден или недоступен"
                await log_to_channel(
                    "API",
                    f"Ошибка GetPlayerSummaries для SteamID: {steam_id}. Профиль не найден.",
                )

            await log_to_channel(
                "API", f"Успешно получен GetPlayerSummaries для SteamID: {steam_id}."
            )
            return result

        except Exception as e:
            await log_error(
                e, f"Ошибка при вызове GetPlayerSummaries для SteamID: {steam_id}"
            )
            raise

    

    async def fetch_steam_data(
        self, steam_id: str, force_refresh: bool = False
    ) -> dict:
        """Получает данные игрока из Steam API с кэшированием"""
        await log_to_channel("API", f"Запрос fetch_steam_data для SteamID: {steam_id}")

        if not self.api_key:
            logger.warning("Steam API key not configured, using fallback mode")
            await log_to_channel(
                "API", f"Steam API key not configured, using fallback mode"
            )
            return {
                "success": False,
                "steamid": None,
                "personaname": None,
                "error_message": "Steam API key не настроен",
            }

        # Получаем только основную информацию о профиле
        player_info = await self.get_player_summary(steam_id)
        
        await log_to_channel(
            "API", f"Успешно получен fetch_steam_data для SteamID: {steam_id}"
        )
        return player_info

    

    def force_cache_clear_for_profile(self, steam_id: str):
        """Принудительно очищает кэш для всех API endpoints этого Steam ID"""
        try:
            from utils.cache import _cache, _lock
            import asyncio

            # Создаем список ключей для удаления
            keys_to_remove = []

            # Ищем все ключи кэша, содержащие этот Steam ID
            for key in _cache.keys():
                if steam_id in key:
                    keys_to_remove.append(key)

            # Удаляем найденные ключи
            for key in keys_to_remove:
                _cache.pop(key, None)
                logger.info(f"🗑️ Очищен кэш для ключа: {key}")

        except Exception as e:
            logger.error(f"Ошибка очистки кэша Steam: {e}")
            log_error(f"Ошибка очистки кэша Steam: {e}")


# Для обратной совместимости
steam_client = SteamAPIClient()


async def fetch_steam_data(steam_id: str, force_refresh: bool = False) -> dict:
    """Функция-обертка для обратной совместимости"""
    return await steam_client.fetch_steam_data(steam_id, force_refresh)
