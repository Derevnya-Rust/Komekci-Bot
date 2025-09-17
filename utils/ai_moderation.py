import json
import asyncio
import os
import logging
import re
import time
from textwrap import dedent
from typing import Optional, NamedTuple

logger = logging.getLogger(__name__)


class NickCheckResult(NamedTuple):
    """Результат проверки никнейма"""
    approve: bool
    public_reasons: list = []
    fixed_full: str = None


# FIX: latin name -> Cyrillic via LLM with heuristics
async def to_cyrillic_name(latin: str) -> Optional[str]:
    """
    Возвращает кириллический вариант имени (если это человеческое имя),
    иначе None. Не бросает исключения.
    """
    # быстрые евристики
    MAP = {
        "yarik": "ярик", "yaroslav": "ярослав", "maksim": "максим",
        "maksym": "максим", "nikita": "никита", "ivan": "иван",
        "alex": "алекс", "alexander": "александр", "dmitry": "дмитрий",
        "dmitri": "дмитрий", "sergey": "сергей", "andrey": "андрей",
        "pavel": "павел", "roman": "роман", "vlad": "влад",
        "vladimir": "владимир", "oleg": "олег", "igor": "игорь"
    }
    low = latin.lower().strip()
    for k, v in MAP.items():
        if low == k:
            return v.capitalize()

    # LLM запрос (строгий JSON)
    prompt = (
        "Верни ТОЛЬКО JSON: {\"name\":\"<Кириллицей или null>\",\"is_human\":true/false}. "
        f"Имя латиницей: \"{latin}\". Если это уменьшительное или ник, верни корректную человеческую форму."
    )
    try:
        # Используем существующий механизм AI запросов
        from cogs.ai import ask_groq
        response = await ask_groq(prompt)

        # Попытка парсинга JSON
        import json
        if response and '{' in response and '}' in response:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            json_str = response[json_start:json_end]
            data = json.loads(json_str)

            if data and data.get("is_human") and data.get("name"):
                return str(data["name"]).strip().title()
    except Exception as e:
        logger.debug(f"Ошибка кириллизации имени '{latin}': {e}")
        pass
    return None

# Глобальный rate-limit для LLM вызовов
_last_llm_call_ts = 0.0

# Технические маркеры, которые не показываем пользователям
TECH_MARKERS = {"LLM_fail_internal", "LLM недоступен или вернул не-JSON", "json_error", "timeout", "LLM недоступен"}

def public_reasons(reasons: list[str]) -> list[str]:
    """Фильтрует технические причины, оставляя только публичные"""
    return [r for r in reasons if r not in TECH_MARKERS]


def _llm_rate_limit_sleep():
    """Применяет rate-limit для LLM вызовов"""
    global _last_llm_call_ts
    dt = time.time() - _last_llm_call_ts
    min_delay = getattr(config, "LLM_MIN_DELAY_SECONDS", 1.6)
    if dt < min_delay:
        time.sleep(min_delay - dt)
    _last_llm_call_ts = time.time()


async def llm_guess_ru_name(name_en: str) -> dict:
    """
    Пытается получить русский эквивалент латинского имени через LLM.
    Возвращает {"is_human_name": bool, "ru": str|None}
    """
    prompt = (
        "Ты помощник модератора. Дано латинское слово, вероятно имя. "
        "Верни ТОЛЬКО JSON:\n"
        "{\n"
        '  "is_human_name": true|false,\n'
        '  "ru": "Имя на кириллице или null"\n'
        "}\n"
        f'Слово: "{name_en}"\n'
        "Если это популярное русское имя в латинице (Alex->Алексей, Yarik->Ярик), верни кириллическую форму."
    )

    try:
        _llm_rate_limit_sleep()

        # FIX: Удваиваем задержку для этого вызова
        await asyncio.sleep(getattr(config, "LLM_MIN_DELAY_SECONDS", 1.6) * getattr(config, "LLM_DELAY_MULTIPLIER", 2))

        from cogs.ai import ask_openrouter
        raw = await asyncio.wait_for(ask_openrouter(prompt), timeout=12.0)

        json_content = extract_json_from_response(raw)
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError:
            logger.warning(f"Ошибка парсинга JSON для имени '{name_en}': {raw[:100]}...")
            return {"is_human_name": False, "ru": None}

        if not isinstance(data, dict):
            return {"is_human_name": False, "ru": None}

        return {
            "is_human_name": bool(data.get("is_human_name", False)),
            "ru": data.get("ru") if data.get("ru") else None
        }

    except Exception as e:
        logger.warning(f"Ошибка LLM-транслитерации для '{name_en}': {e}")
        return {"is_human_name": False, "ru": None}


async def guess_cyrillic_first_name_with_llm(name_latin: str) -> Optional[str]:
    """
    Пытаемся получить кириллический эквивалент латинского имени через LLM.
    Возвращает кириллическое имя или None.
    """
    prompt = (
        "Ты модератор ников. Дано латинское слово, вероятно, человеческое имя. "
        "Верни ТОЛЬКО JSON одним объектом без лишнего текста:\n"
        "{\n"
        '  "is_human_first_name": true|false,\n'
        '  "cyrillic": "<Имя на кириллице или пусто если нет>",\n'
        '  "confidence": 0.0..1.0\n'
        "}\n"
        f'Слово: "{name_latin}"\n'
        "Требования: если это форма русского имени (напр. Yarik -> Ярик), верни корректную форму на кириллице. "
        "Без комментариев вне JSON."
    )

    try:
        _llm_rate_limit_sleep()

        # FIX: Удваиваем задержку для этого вызова
        await asyncio.sleep(getattr(config, "LLM_MIN_DELAY_SECONDS", 1.6) * getattr(config, "LLM_DELAY_MULTIPLIER", 2))

        # Используем существующие функции из cogs.ai
        from cogs.ai import ask_openrouter
        raw = await asyncio.wait_for(ask_openrouter(prompt), timeout=12.0)

        # Парсим устойчиво
        json_content = extract_json_from_response(raw)
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None
        if not data.get("is_human_first_name"):
            return None

        cyr = (data.get("cyrillic") or "").strip()
        if cyr:
            return cyr
        return None

    except Exception as e:
        logger.warning(f"Ошибка LLM-транслитерации для '{name_latin}': {e}")
        return None

SYSTEM_PROMPT = dedent("""
Ты — модератор никнеймов сообщества «Деревня». Реши, можно ли одобрить строку формата «SteamNick | Имя» и при необходимости предложи исправление.

КРИТИЧЕСКИ ВАЖНО - ФОРМАТ:
Формат СТРОГО: "SteamNick | Имя" 
- Слева от " | " идёт игровой ник Steam (латиница/кириллица)
- Справа от " | " идёт ТОЛЬКО реальное имя человека (кириллица)
- Разделитель " | " ЕДИНСТВЕННЫЙ в строке с пробелами по бокам

ПРАВИЛА:
1) Ровно один разделитель " | " (пробел-вертикальная черта-пробел)
2) Каждая часть 3–20 символов
3) SteamNick (слева): латиница/кириллица, цифры, пробел, "_", "-". БЕЗ эмодзи, обёрток, многоточий
4) Имя (справа): ТОЛЬКО кириллица, начинается с заглавной. Уменьшительные допустимы (Ваня, Лёша)
5) Запрещена нецензурная лексика
6) Запрещены псевдо-имена: игрок, player, gamer, user, чувак, парень

ПРИМЕРЫ ПРАВИЛЬНЫХ:
- "Sulio | Сулейман" 
- "Western | Максим"
- "Player123 | Ваня"

ПРИМЕРЫ НЕПРАВИЛЬНЫХ:
- "Western | Western |Максим" (дубль + два разделителя - НЕДОПУСТИМО!)
- "Nick | Nick" (дубль имени)
- "Steam | Alex" (латинское имя)

КРИТИЧЕСКИ ВАЖНО ПРИ ИСПРАВЛЕНИИ:
- НИКОГДА не дублируй SteamNick в части имени
- Убирай ВСЕ лишние разделители " | "
- Оставляй ТОЛЬКО один разделитель " | "
- Справа от разделителя ТОЛЬКО реальное имя на кириллице

Верни СТРОГО JSON:
{
  "approve": true|false,
  "reasons": ["кратко по пунктам"],
  "fixed_full": "Исправленный SteamNick | Имя или null",
  "notes_to_user": "1–2 коротких предложения"
}
""")


def build_user_prompt(full: str) -> str:
    return f'Проверь никнейм по правилам формата "SteamNick | Имя". При исправлении НЕ дублируй SteamNick в части имени.\n\nПроверяемый никнейм: "{full}"\n\nВерни только JSON.'


def extract_json_from_response(content: str) -> str:
    """Извлекает JSON из ответа LLM, очищая от кодовых блоков и лишнего текста"""
    content = content.strip()

    # Попытка 1: JSON в кодовом блоке
    json_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_block_match:
        return json_block_match.group(1)

    # Попытка 2: JSON объект в конце строки
    json_match = re.search(r'(\{.*\})\s*$', content, re.DOTALL)
    if json_match:
        return json_match.group(1)

    # Попытка 3: весь контент как JSON
    return content


async def llm_decide(full: str) -> NickCheckResult:
    """Проверка никнейма через LLM с жёстким парсингом JSON"""
    provider = getattr(config, "NICKCHECK_PROVIDER", "openrouter").lower()

    try:
        # Импортируем функции из cogs.ai
        from cogs.ai import ask_groq, ask_openrouter

        user_prompt = build_user_prompt(full)
        full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

        # Применяем rate-limit
        _llm_rate_limit_sleep()

        # FIX: Удваиваем задержку для этого вызова
        await asyncio.sleep(getattr(config, "LLM_MIN_DELAY_SECONDS", 1.6) * getattr(config, "LLM_DELAY_MULTIPLIER", 2))

        # Таймаут 12 секунд
        if provider == "groq":
            logger.info(f"Используем Groq для проверки никнейма: {full}")
            raw = await asyncio.wait_for(ask_groq(full_prompt), timeout=12.0)
        else:
            logger.info(f"Используем OpenRouter для проверки никнейма: {full}")
            raw = await asyncio.wait_for(ask_openrouter(full_prompt), timeout=12.0)

        # Извлекаем и парсим JSON
        json_content = extract_json_from_response(raw)
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.warning(f"Ошибка парсинга JSON от LLM для '{full}': {e}")
            logger.warning(f"Сырой ответ: {raw[:200]}...")
            return NickCheckResult(
                False,
                ["не удалось автоматически проверить—повторите"],
                None
            )

        return NickCheckResult(
            bool(data.get("approve", False)),
            list(data.get("reasons", [])),
            data.get("fixed_full"),
        )

    except asyncio.TimeoutError:
        logger.warning(f"Таймаут LLM проверки никнейма '{full}'")
        return NickCheckResult(
            False,
            ["не удалось автоматически проверить—повторите"],
            None
        )
    except Exception as e:
        logger.warning(f"Ошибка LLM проверки никнейма '{full}': {e}")
        return NickCheckResult(
            False,
            ["не удалось автоматически проверить—повторите"],
            None
        )


def _hard_check_full_local(full: str) -> NickCheckResult:
    """Локальная строгая проверка никнейма"""
    # Локальный импорт для избежания циклических зависимостей
    from utils.nickname_moderator import NicknameModerator
    import asyncio

    # Создаем новый event loop если его нет
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Запускаем асинхронную функцию
    r = loop.run_until_complete(NicknameModerator().check_nickname(full))
    return NickCheckResult(r["approve"], list(r["reasons"]), r.get("fixed_full"))


async def decide_nickname(nickname: str) -> NickCheckResult:
    """Простая проверка никнейма без AI"""
    # Базовая проверка формата
    if " | " not in nickname:
        return NickCheckResult(
            approve=False,
            public_reasons=["Никнейм должен быть в формате 'SteamNick | Имя'"],
            fixed_full=None
        )

    parts = nickname.split(" | ")
    if len(parts) != 2:
        return NickCheckResult(
            approve=False,
            public_reasons=["Неправильный формат никнейма"],
            fixed_full=None
        )

    steam_nick, real_name = parts

    # Проверяем на пустые части
    if not steam_nick.strip() or not real_name.strip():
        return NickCheckResult(
            approve=False,
            public_reasons=["Никнейм и имя не могут быть пустыми"],
            fixed_full=None
        )

    # Проверяем заглавную букву в имени
    if real_name and real_name[0].islower():
        fixed_name = real_name.capitalize()
        return NickCheckResult(
            approve=False,
            public_reasons=["Имя должно начинаться с заглавной буквы"],
            fixed_full=f"{steam_nick} | {fixed_name}"
        )

    # Если все проверки пройдены
    return NickCheckResult(approve=True)