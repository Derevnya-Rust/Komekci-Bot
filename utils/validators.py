import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def is_valid_nickname(nickname: str) -> Tuple[bool, str, str]:
    """Проверяет валидность никнейма"""
    if not nickname or len(nickname.strip()) == 0:
        return False, "Никнейм не может быть пустым", ""

    # Проверяем формат SteamNick | Имя
    if " | " not in nickname:
        return False, "Никнейм должен быть в формате 'SteamNick | Имя'", ""

    parts = nickname.split(" | ")
    if len(parts) != 2:
        return False, "Никнейм должен содержать только один разделитель ' | '", ""

    steam_nick, real_name = parts

    if not steam_nick.strip():
        return False, "Steam никнейм не может быть пустым", ""

    if not real_name.strip():
        return False, "Имя не может быть пустым", ""

    # Проверяем на недопустимые символы
    if re.search(r'[♛☬卍]', nickname):
        return False, "Никнейм содержит недопустимые символы", ""

    return True, "", ""


def parse_discord_nick(nickname: str) -> str:
    """Извлекает чистый никнейм из Discord никнейма"""
    if " | " in nickname:
        return nickname.split(" | ")[0].strip()
    return nickname.strip()


def nick_matches(nick1: str, nick2: str) -> bool:
    """Проверяет совпадение никнеймов"""
    clean1 = parse_discord_nick(nick1).lower()
    clean2 = parse_discord_nick(nick2).lower()
    return clean1 == clean2


def is_nickname_format_valid(nickname: str) -> bool:
    """Проверяет формат никнейма"""
    valid, _, _ = is_valid_nickname(nickname)
    return valid


def hard_check_full(nickname: str) -> Tuple[bool, list, Optional[str]]:
    """Строгая проверка никнейма"""
    valid, error_msg, _ = is_valid_nickname(nickname)
    if not valid:
        return False, [error_msg], None
    return True, [], None


def auto_fix_nickname(nickname: str) -> Tuple[str, list]:
    """Автоматическое исправление никнейма"""
    fixes = []
    fixed = nickname

    # Исправляем разделитель
    if "|" in fixed and " | " not in fixed:
        fixed = fixed.replace("|", " | ")
        fixes.append("Исправлен разделитель на ' | '")

    # Капитализация имени
    if " | " in fixed:
        parts = fixed.split(" | ")
        if len(parts) == 2:
            steam_nick, real_name = parts
            if real_name and real_name[0].islower():
                real_name = real_name.capitalize()
                fixed = f"{steam_nick} | {real_name}"
                fixes.append("Исправлена заглавная буква в имени")

    return fixed, fixes


def extract_discord_id(text: str) -> Optional[str]:
    """Извлекает Discord ID из текста"""
    match = re.search(r'(\d{17,19})', text)
    return match.group(1) if match else None