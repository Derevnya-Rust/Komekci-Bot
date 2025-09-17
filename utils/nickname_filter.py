import re
import logging

logger = logging.getLogger(__name__)

# Простой список запрещенных слов
BANNED_WORDS = [
    "admin", "moderator", "bot", "vlg", "деревня",
    # Добавьте сюда другие запрещенные слова
]


class NicknameFilter:
    """Простой фильтр никнеймов"""

    def __init__(self):
        self.banned_words_full = BANNED_WORDS.copy()

    def is_banned(self, nickname: str) -> bool:
        """Проверяет, запрещен ли никнейм"""
        nickname_lower = nickname.lower()
        return any(word in nickname_lower for word in self.banned_words_full)


# Глобальный экземпляр фильтра
nickname_filter = NicknameFilter()


def filter_nickname(nickname: str) -> tuple[bool, str, str]:
    """
    Фильтрует никнейм на предмет неподобающего содержимого

    Returns:
        tuple: (is_blocked, reason, user_message)
    """
    try:
        # Проверяем запрещенные слова
        if nickname_filter.is_banned(nickname):
            return True, "Содержит запрещенные слова", "Никнейм содержит недопустимые слова"

        # Проверяем на недопустимые символы
        if re.search(r'[♛☬卍]', nickname):
            return True, "Недопустимые символы", "Никнейм содержит недопустимые символы"

        # Если все проверки пройдены
        return False, "", ""

    except Exception as e:
        logger.error(f"Ошибка фильтрации никнейма: {e}")
        return False, "", ""