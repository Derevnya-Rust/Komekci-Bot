import re
import asyncio
import time
import logging
import aiohttp
import discord
from datetime import datetime, timezone

from handlers.steam_api import fetch_steam_data, get_steamid64_from_url, steam_client
from utils.cache import get_cached, set_cache
from utils.validators import parse_discord_nick, nick_matches, is_nickname_format_valid, hard_check_full
from utils.misc import extract_real_name_from_discord_nick
from utils.logger import get_module_logger

logger = get_module_logger(__name__)


def _are_nicknames_completely_different(nick1, nick2):
    """Проверяет, являются ли никнеймы кардинально разными (разные алфавиты или стили)"""
    if not nick1 or not nick2:
        return True

    # Проверяем основные алфавиты
    has_cyrillic_1 = bool(re.search(r"[а-яё]", nick1, re.IGNORECASE))
    has_latin_1 = bool(re.search(r"[a-z]", nick1, re.IGNORECASE))
    has_cyrillic_2 = bool(re.search(r"[а-яё]", nick2, re.IGNORECASE))
    has_latin_2 = bool(re.search(r"[a-z]", nick2, re.IGNORECASE))

    # Если один ник только на кириллице, а другой только на латинице - это разные ники
    if (has_cyrillic_1 and not has_latin_1) and (has_latin_2 and not has_cyrillic_2):
        return True
    if (has_latin_1 and not has_cyrillic_1) and (has_cyrillic_2 and not has_latin_2):
        return True

    # Проверяем на совершенно разные стили (например, XOMKI4 vs Киянка)
    # Если один содержит цифры, а другой нет, и при этом сходство очень низкое
    has_digits_1 = bool(re.search(r"\d", nick1))
    has_digits_2 = bool(re.search(r"\d", nick2))

    if has_digits_1 != has_digits_2:
        # Вычисляем сходство без цифр для более точной проверки
        clean_nick1 = re.sub(r"\d", "", nick1)
        clean_nick2 = re.sub(r"\d", "", nick2)
        if clean_nick1 and clean_nick2:
            similarity = _calculate_nickname_similarity(clean_nick1, clean_nick2)
            if similarity < 0.3:  # Очень низкое сходство
                return True

    return False


def _calculate_nickname_similarity(nick1, nick2):
    """Вычисляет сходство между двумя никнеймами (от 0 до 1)"""
    if not nick1 or not nick2:
        return 0.0

    # Удаляем специальные символы и цифры в конце для более точного сравнения
    clean_nick1 = re.sub(r"[^a-zA-Zа-яё]", "", nick1.lower())
    clean_nick2 = re.sub(r"[^a-zA-Zа-яё]", "", nick2.lower())

    if not clean_nick1 or not clean_nick2:
        return 0.0

    if clean_nick1 == clean_nick2:
        return 1.0

    # Проверяем вхождение одного в другой
    if clean_nick1 in clean_nick2 or clean_nick2 in clean_nick1:
        shorter = min(len(clean_nick1), len(clean_nick2))
        longer = max(len(clean_nick1), len(clean_nick2))
        return shorter / longer

    # Алгоритм Левенштейна для более точного сравнения
    def levenshtein_distance(s1, s2):
        if len(s1) > len(s2):
            s1, s2 = s2, s1

        distances = list(range(len(s1) + 1))
        for i2, c2 in enumerate(s2):
            distances_ = [i2 + 1]
            for i1, c1 in enumerate(s1):
                if c1 == c2:
                    distances_.append(distances[i1])
                else:
                    distances_.append(
                        1 + min((distances[i1], distances[i1 + 1], distances_[-1]))
                    )
            distances = distances_
        return distances[-1]

    max_len = max(len(clean_nick1), len(clean_nick2))
    if max_len == 0:
        return 1.0

    distance = levenshtein_distance(clean_nick1, clean_nick2)
    similarity = 1 - (distance / max_len)

    return max(0.0, similarity)


def get_account_age_days(member) -> int:
    """Считает возраст аккаунта Discord в днях."""
    return (datetime.now(timezone.utc) - member.created_at).days


def extract_steam_links(text) -> list:
    """Извлекает Steam ссылки из текста"""
    # Проверяем тип входящего параметра
    if not isinstance(text, str):
        text = str(text)

    logger.debug(f"Извлечение Steam ссылок из: {text}")

    # Регулярное выражение для Steam ссылок
    steam_pattern = r'https://steamcommunity\.com/(?:profiles|id)/[a-zA-Z0-9_-]+/?'

    # Ищем все совпадения
    matches = re.finditer(steam_pattern, text)
    links = [match.group() for match in matches]

    logger.debug(f"Найдено Steam ссылок: {len(links)}")
    return links


def extract_steam_links_from_embed(
    embed, target_player_name=None, target_player_id=None
):
    """
    Извлекает Steam-ссылки из Discord embed'а.

    Args:
        embed: Discord embed объект
        target_player_name: имя игрока для проверки принадлежности (опционально)
        target_player_id: ID игрока для проверки принадлежности (опционально)

    Returns:
        List[str]: список найденных Steam-ссылок
    """
    steam_links = []

    if not embed:
        return steam_links

    logger.debug(
        f"🔍 Анализируем embed: title='{embed.title}', description='{embed.description[:100] if embed.description else 'None'}...'"
    )

    # РАСШИРЕННАЯ проверка на анкету - более гибкие критерии
    is_application_embed = False

    # 1. Проверяем заголовок
    if embed.title:
        title_lower = embed.title.lower()
        application_keywords = [
            "анкета",
            "заявка",
            "application",
            "форма",
            "готова к рассмотрению",
        ]
        is_application_embed = any(
            keyword in title_lower for keyword in application_keywords
        )
        logger.debug(
            f"📋 Проверка заголовка на анкету: '{embed.title}' -> {is_application_embed}"
        )

    # 2. Проверяем наличие Steam-полей в embed'е
    if not is_application_embed and embed.fields:
        steam_field_keywords = [
            "steam",
            "стим",
            "профиль",
            "ссылка на ваш steam",
            "раньше играли",
            "сколько часов",
            "время в игре",
        ]

        for field in embed.fields:
            if field.name:
                field_name_lower = field.name.lower()
                if any(keyword in field_name_lower for keyword in steam_field_keywords):
                    is_application_embed = True
                    logger.debug(
                        f"📋 Проверка поля на анкету: '{field.name}' -> {is_application_embed}"
                    )
                    break

    # 3. Если есть поля с типичными вопросами анкеты - считаем анкетой
    if not is_application_embed and embed.fields and len(embed.fields) >= 2:
        typical_questions = [
            "раньше играли",
            "сколько часов",
            "время",
            "опыт",
            "возраст",
            "откуда узнали",
            "друг",
            "сервер",
        ]

        field_matches = 0
        for field in embed.fields:
            if field.name:
                field_name_lower = field.name.lower()
                if any(keyword in field_name_lower for keyword in typical_questions):
                    field_matches += 1

        if field_matches >= 2:  # Если есть 2+ типичных вопроса анкеты
            is_application_embed = True
            logger.debug(
                f"📋 Обнаружена анкета по типичным вопросам: {field_matches} совпадений"
            )

    # 4. Если нашли Steam-ссылку в любом поле - вероятно это анкета
    if not is_application_embed and embed.fields:
        for field in embed.fields:
            if field.value and "steamcommunity.com" in field.value:
                is_application_embed = True
                logger.debug(f"📋 Обнаружена Steam-ссылка в поле - считаем анкетой")
                break

    # Если это НЕ анкета - не извлекаем Steam-ссылки
    if not is_application_embed:
        logger.debug(
            f"🚫 Embed не является анкетой, пропускаем извлечение Steam-ссылок"
        )
        return steam_links

    logger.info(f"✅ Подтверждено: это embed анкеты")

    # Извлекаем Steam-ссылки из описания
    if embed.description:
        description_links = extract_steam_links(embed.description)
        steam_links.extend(description_links)
        if description_links:
            logger.info(
                f"🔗 Найдены Steam-ссылки в описании embed'а: {description_links}"
            )

    # Извлекаем Steam-ссылки из полей
    if embed.fields:
        logger.debug(f"📋 Проверяем {len(embed.fields)} полей embed'а...")

        for field in embed.fields:
            if not field.value:
                continue

            field_name_lower = field.name.lower() if field.name else ""
            field_value = field.value.strip()

            logger.debug(f"🔍 Поле: '{field.name}' = '{field_value[:50]}...'")

            # Ищем Steam-ссылки во всех полях
            field_links = extract_steam_links(field_value)
            if field_links:
                steam_links.extend(field_links)
                logger.info(
                    f"🔗 Найдены Steam-ссылки в поле '{field.name}': {field_links}"
                )

                # Приоритетные поля для Steam-ссылок
                steam_priority_keywords = [
                    "ссылка на ваш steam-профиль",
                    "steam-профиль",
                    "steam профиль",
                    "ссылка на steam",
                    "steam ссылка",
                    "steam",
                ]

                is_priority_field = any(
                    keyword in field_name_lower for keyword in steam_priority_keywords
                )
                if is_priority_field:
                    logger.info(
                        f"🔗 [ПРИОРИТЕТНОЕ ПОЛЕ] Steam-ссылки в приоритетном поле '{field.name}': {field_links}"
                    )
                    # Перемещаем приоритетные ссылки в начало списка
                    for link in reversed(field_links):
                        if link in steam_links:
                            steam_links.remove(link)
                            steam_links.insert(0, link)

    # Нормализуем и удаляем дубликаты, сохраняя порядок
    unique_links = []
    for link in steam_links:
        normalized_link = normalize_steam_url(link)
        if normalized_link not in unique_links:
            unique_links.append(normalized_link)
            if normalized_link != link:
                logger.info(
                    f"🔧 Steam URL нормализован в embed: {link} → {normalized_link}"
                )

    if not unique_links:
        logger.warning(f"⚠️ Steam-ссылки не найдены в embed'е")
    else:
        logger.info(
            f"✅ Найдено уникальных Steam-ссылок в embed'е: {len(unique_links)} - {unique_links}"
        )

    return unique_links


def normalize_steam_url(steam_url: str) -> str:
    """Нормализует Steam URL, преобразуя Steam ID в полную ссылку если нужно"""
    if not steam_url:
        return ""

    # Если это уже полная ссылка, очищаем от лишних частей
    if steam_url.startswith("https://steamcommunity.com/"):
        # Удаляем лишние части URL типа /edit/settings, /games, /badges и т.д.
        clean_url = steam_url

        # Паттерны для очистки URL
        cleanup_patterns = [
            r"/edit/settings.*$",
            r"/edit.*$",
            r"/games.*$",
            r"/badges.*$",
            r"/friends.*$",
            r"/groups.*$",
            r"/screenshots.*$",
            r"/images.*$",
            r"/videos.*$",
            r"/workshop.*$",
            r"/inventory.*$",
            r"/reviews.*$",
            r"/recommended.*$",
            r"/\?.*$",  # убираем query параметры
            r"#.*$",  # убираем якори
        ]

        for pattern in cleanup_patterns:
            clean_url = re.sub(pattern, "", clean_url)

        # Убираем trailing slash если есть
        clean_url = clean_url.rstrip("/")

        # Возвращаем очищенный URL
        return clean_url

    # Если это Steam ID (17-цифровое число), преобразуем в полную ссылку
    steam_id_pattern = r"^\d{17}$"
    if re.match(steam_id_pattern, steam_url.strip()):
        return f"https://steamcommunity.com/profiles/{steam_url.strip()}"

    # Если это не полная ссылка и не Steam ID, возвращаем как есть
    return steam_url


def extract_steam_id_from_url(steam_url: str) -> str | None:
    """Извлекает Steam ID из URL"""
    if not steam_url:
        return None

    # Проверяем на фейковые домены
    fake_domains = [
        "xn--steamcommunity-vul.com",
        "steamcommunlty.com",  # пропущена буква i
        "steamcommunitty.com",  # двойная t
        "steamcommunity.ru",
        "steamcommunity.org",
    ]

    for fake_domain in fake_domains:
        if fake_domain in steam_url.lower():
            logger.warning(f"🚨 Обнаружен поддельный домен: {fake_domain}")
            return None

    # Проверяем правильный домен
    if "steamcommunity.com" not in steam_url.lower():
        logger.warning(f"❌ Неправильный домен в URL: {steam_url}")
        return None

    # Извлекаем ID из profiles/ или id/
    if "/profiles/" in steam_url:
        match = re.search(r"/profiles/(\d+)", steam_url)
        if match:
            steam_id = match.group(1)
            logger.info(f"🆔 Извлечен SteamID64 из profiles/: {steam_id}")
            return steam_id
    elif "/id/" in steam_url:
            match = re.search(r"/id/([^/]+)", steam_url)
            if match:
                vanity_name = match.group(1)
                logger.info(f"🔗 Найден Vanity URL: {vanity_name}, начинаем конвертацию → SteamID64")
                try:
                    from handlers.steam_api import get_steamid64_from_url
                    steam_id64 = asyncio.run(get_steamid64_from_url(steam_url))
                    if steam_id64:
                        logger.info(f"✅ Vanity URL '{vanity_name}' преобразован в SteamID64: {steam_id64}")
                        return steam_id64
                    else:
                        logger.error(f"❌ Не удалось конвертировать Vanity URL '{vanity_name}' в SteamID64")
                        return None
                except Exception as e:
                    logger.error(f"❌ Ошибка при конвертации Vanity URL: {e}")
                    return None

    logger.warning(f"❌ Не удалось извлечь ID из URL: {steam_url}")
    return None


async def check_steam_profile_and_nickname(
    steam_url: str, discord_nickname: str, user: discord.Member
) -> dict:
    """
    Проверяет Steam-профиль и сравнивает никнейм.
    Возвращает детальную информацию о результатах проверки.
    """
    logger.info(
        f"🔍 Детальная проверка Steam-профиля для {user.display_name}: {steam_url}"
    )

    result = {
        "valid_url": False,
        "steam_nickname": "",
        "discord_nickname": discord_nickname,
        "nickname_matches": False,
        "error_message": "",
        "auto_fix_applied": False,
        "auto_fix_message": "",
        "original_nickname": discord_nickname,
    }

    # Шаг 1: Проверка и нормализация URL
    try:
        normalized_url = normalize_steam_url(steam_url)
        logger.info(f"🔧 Нормализованный URL: {normalized_url}")

        steam_id = extract_steam_id_from_url(normalized_url)
        if not steam_id:
            result["error_message"] = "❌ Не удалось преобразовать Steam URL в SteamID64"
            logger.error(f"❌ Не удалось преобразовать Steam URL в SteamID64: {steam_url}")
            return result

        result["valid_url"] = True
        logger.info(f"✅ Steam URL валидный, извлечен ID: {steam_id}")

    except Exception as e:
        result["error_message"] = f"❌ Ошибка обработки ссылки: {str(e)}"
        logger.error(f"❌ Ошибка обработки ссылки {steam_url}: {e}")
        return result

    # Шаг 2: Получение данных из Steam API
    try:
        from handlers.steam_api import steam_client

        logger.info(f"🌐 Запрос данных Steam API для ID: {steam_id}")
        steam_data = await steam_client.fetch_steam_data(steam_id)

        if not steam_data or not steam_data.get("success"):
            result["error_message"] = steam_data.get("error_message", "❌ Не удалось получить данные Steam профиля")
            return result

        # Получаем Steam никнейм
        steam_nickname = steam_data.get("personaname", "")
        if not steam_nickname:
            result["error_message"] = "❌ Не удалось получить никнейм из Steam профиля"
            logger.error(f"❌ Пустой Steam никнейм для {steam_id}")
            return result

        result["steam_nickname"] = steam_nickname
        logger.info(f"✅ Steam никнейм получен: '{steam_nickname}'")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка Steam API: {e}")
        result["error_message"] = f"❌ Ошибка Steam API: {str(e)}"
        return result

    # Шаг 3: Проверка совпадения никнеймов
    try:

        # Получаем текущий никнейм пользователя
        current_user_nick = user.display_name

        # Парсим левую часть Discord ника
        discord_left = parse_discord_nick(current_user_nick)

        logger.info(f"🔍 Сравнение ников:")
        logger.info(f"  Steam: '{steam_nickname}'")
        logger.info(f"  Discord full: '{current_user_nick}'")
        logger.info(f"  Discord left: '{discord_left}'")

        # Сравниваем ники
        matches = nick_matches(steam_nickname, discord_left)
        result["nickname_matches"] = matches

        if matches:
            logger.info(f"✅ Ники совпадают")
        else:
            logger.info(f"⚠️ Ники не совпадают")

            # КРИТИЧЕСКАЯ ПРОВЕРКА: НЕ применяем автоисправление если имя содержит латинские буквы
            real_name = extract_real_name_from_discord_nick(current_user_nick)

            # СТРОГАЯ проверка: любая латинская буква в имени = БЛОКИРОВКА автоисправления
            if re.search(r"[a-zA-Z]", real_name):
                result["error_message"] = (
                    f"❌ **КРИТИЧЕСКАЯ ОШИБКА: Латинское имя в Discord нике!**\n\n"
                    f"**Текущий ник:** `{current_user_nick}`\n"
                    f"**Проблема:** Имя `{real_name}` содержит латинские буквы\n\n"
                    f"🚫 **СТРОГОЕ требование:** Используйте ТОЛЬКО кириллицу (русские буквы) в имени!\n"
                    f"✅ **Исправьте на:** `{steam_nickname} | ВашеИмяКириллицей`\n\n"
                    f"**Примеры правильных имен:** Михаил, Сергей, Анна, Дмитрий"
                )
                logger.error(f"🚫 БЛОКИРОВКА автоисправления: имя '{real_name}' содержит латинские буквы")
                return result

            suggested_nick = f"{steam_nickname} | {real_name}"

            # Валидируем предложенный ник
            is_valid, reason, auto_fix_result = is_nickname_format_valid(suggested_nick)

            if is_valid or (auto_fix_result and auto_fix_result.get("auto_applied")):
                try:
                    # Применяем автоисправление ТОЛЬКО если имя кириллическое
                    final_nick = auto_fix_result.get("fixed_nickname", suggested_nick) if auto_fix_result else suggested_nick

                    await user.edit(
                        nick=final_nick,
                        reason=f"Автоисправление: Steam ник '{steam_nickname}' не совпадал с Discord '{discord_left}'"
                    )

                    result["nickname_matches"] = True
                    result["auto_fix_applied"] = True
                    result["auto_fix_message"] = (
                        f"🔧 **Никнейм автоматически исправлен!**\n\n"
                        f"**Было:** `{current_user_nick}`\n"
                        f"**Стало:** `{final_nick}`\n\n"
                        f"✅ Теперь ваш Discord никнейм соответствует Steam никнейму!"
                    )
                    result["original_nickname"] = current_user_nick

                    logger.info(f"🔧 Автоисправление применено: '{current_user_nick}' → '{final_nick}'")

                except discord.Forbidden:
                    logger.warning(f"⚠️ Нет прав для изменения ника у {user.display_name}")
                    result["error_message"] = (
                        f"❌ **Ники не совпадают:**\n"
                        f"• **Discord:** `{discord_left}`\n"
                        f"• **Steam:** `{steam_nickname}`\n\n"
                        f"🔧 **Как исправить:**\n"
                        f"Измените ваш Discord ник на: `{suggested_nick}`"
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка автоисправления ника: {e}")
                    result["error_message"] = f"❌ Ошибка исправления ника: {str(e)}"
            else:
                # Не удалось автоисправить
                result["error_message"] = (
                    f"❌ **Ники не совпадают:**\n"
                    f"• **Discord:** `{discord_left}`\n" 
                    f"• **Steam:** `{steam_nickname}`\n\n"
                    f"🔧 **Измените один из них для совпадения**"
                )

    except Exception as e:
        logger.error(f"❌ Ошибка проверки никнеймов: {e}")
        result["error_message"] = f"❌ Ошибка сравнения никнеймов: {str(e)}"
        return result

    logger.info(f"✅ Проверка завершена для {user.display_name}: nickname_matches={result['nickname_matches']}")
    return result


def create_application_embed(
    user: discord.User,
    steam_url: str,
    result: dict,
    channel: discord.TextChannel,
    discord_nickname: str,
):
    """Создает embed сообщение с результатами проверки заявки."""
    embed = discord.Embed(
        title="Проверка заявки на вступление",
        description=f"Пользователь: {user.mention}\nSteam-профиль: {steam_url}",
        color=discord.Color.blue(),
    )

    # Добавляем информацию о пользователе
    embed.set_author(
        name=f"{user.name}#{user.discriminator}",
        icon_url=user.avatar.url if user.avatar else discord.Embed.Empty,
    )

    # Добавляем информацию о Steam профиле
    if result.get("steam_nickname"):
        embed.add_field(
            name="Steam Никнейм", value=f"`{result['steam_nickname']}`", inline=True
        )

    # Добавляем информацию о Discord никнейме
    original_nickname_display = (
        result.get("original_nickname", discord_nickname)
        if result.get("auto_fix_applied")
        else discord_nickname
    )
    if original_nickname_display:
        embed.add_field(
            name="Discord Никнейм", value=f"`{original_nickname_display}`", inline=True
        )

    # Добавляем информацию о совпадении никнеймов
    if "nickname_matches" in result:
        match_status = (
            "✅ Совпадают" if result["nickname_matches"] else "❌ Не совпадают"
        )
        embed.add_field(name="Совпадение никнеймов", value=match_status, inline=False)

    # Убираем поле про часы в Rust, так как оно удалено
    # if "rust_playtime_minutes" in result:
    #     rust_minutes = result["rust_playtime_minutes"]
    #     rust_hours = rust_minutes // 60
    #     embed.add_field(
    #         name="Rust Время", value=f"{rust_minutes} мин ({rust_hours} ч)", inline=True
    #     )


    # Убираем поле про доступность профиля
    # if "profile_accessible" in result:
    #     profile_status = (
    #         "✅ Доступен" if result["profile_accessible"] else "❌ Приватный"
    #     )
    #     embed.add_field(name="Steam Профиль", value=profile_status, inline=True)

    # Добавляем информацию об автоисправлении, если оно было применено
    if result.get("auto_fix_applied"):
        embed.add_field(
            name="🔧 Автоисправление никнейма",
            value=f"**Было:** `{result['original_nickname']}`\n**Стало:** `{result['fixed_nickname']}`\n\n"
            + result.get("auto_fix_message", ""),
            inline=False,
        )

    # Добавляем поля с результатами проверки
    if result.get("warnings"):
        embed.add_field(
            name="⚠️ Предупреждения",
            value="\n".join(result["warnings"])[:1024],
            inline=False,
        )

    # Определяем статус заявки
    if result.get("error_message"):
        status_color = 0xFF0000  # Красный - ошибка
        status_title = "❌ Заявка отклонена автоматически"
        status_description = result["error_message"]
    elif result.get("auto_fix_applied"):
        status_color = 0x3498DB  # Синий - автоисправление
        status_title = "🔧 Заявка с автоисправлением"
        status_description = result.get("auto_fix_message", "Никнейм был автоматически исправлен.")
    elif result.get("warnings"):
        status_color = 0xFFA500  # Оранжевый - предупреждения
        status_title = "⚠️ Заявка требует проверки"
        status_description = "Найдены проблемы, требующие внимания модератора"
    else:
        status_color = 0x00FF00  # Зеленый - все хорошо
        status_title = "✅ Заявка готова к рассмотрению"
        status_description = "Все проверки пройдены успешно"

    embed.add_field(name=status_title, value=status_description, inline=False)
    embed.color = discord.Color(
        status_color
    )  # Устанавливаем цвет в зависимости от статуса

    return embed


def check_nickname_match(discord_nickname: str, steam_nickname: str) -> dict:
    """Проверяет совпадение никнеймов Discord и Steam"""
    result = {"matches": False, "suggestion": None}

    if not discord_nickname or not steam_nickname:
        return result

    # Простая проверка на точное совпадение
    if discord_nickname.lower() == steam_nickname.lower():
        result["matches"] = True
        return result

    # Проверка формата "SteamNick | Имя"
    if " | " in discord_nickname:
        steam_part = discord_nickname.split(" | ")[0].strip()
        if steam_part.lower() == steam_nickname.lower():
            result["matches"] = True
            return result

    # Проверка сходства
    similarity = _calculate_nickname_similarity(discord_nickname, steam_nickname)
    if similarity > 0.8:
        result["matches"] = True
        return result

    # Предложение исправления
    if not " | " in discord_nickname:
        result["suggestion"] = f"Измените никнейм на: {steam_nickname} | Имя"

    return result


def extract_discord_id(text: str) -> int | None:
    """Извлекает Discord ID (17–20 цифр) из текста."""
    if not text:
        return None

    # Ищем Discord упоминания <@!ID> или <@ID>
    mention_match = re.search(r"<@!?(\d{17,20})>", text)
    if mention_match:
        return int(mention_match.group(1))

    # Ищем просто длинные числа (Discord ID)
    id_match = re.search(r"\b(\d{17,20})\b", text)
    if id_match:
        return int(id_match.group(1))

    return None