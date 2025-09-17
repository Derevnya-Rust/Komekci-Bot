import logging
from utils.validators import is_valid_nickname, auto_fix_nickname
from utils.decision import NickCheckResult

logger = logging.getLogger(__name__)


class NicknameModerator:
    """Модератор никнеймов"""

    def __init__(self):
        pass

    @staticmethod
    async def check_nickname(user, nickname: str) -> NickCheckResult:
        """Проверяет никнейм по правилам модерации"""
        try:
            logger.info(f"🔍 Начинаю проверку никнейма: '{nickname}' для пользователя {user.display_name if hasattr(user, 'display_name') else 'Unknown'}")

            # Используем валидатор
            is_valid, error_message, _ = is_valid_nickname(nickname)

            if is_valid:
                logger.info(f"✅ Никнейм '{nickname}' прошел проверку")
                return NickCheckResult(
                    approve=True,
                    reasons=[],
                    fixed_full=None,
                    notes_to_user="Никнейм соответствует требованиям"
                )
            else:
                logger.info(f"❌ Никнейм '{nickname}' не прошел проверку: {error_message}")

                # Пытаемся исправить
                fixed_nick, fixes = auto_fix_nickname(nickname)

                if fixes:
                    logger.info(f"🔧 Предложено исправление для '{nickname}': '{fixed_nick}' (применены: {', '.join(fixes)})")
                    notes = f"Предложены исправления: {', '.join(fixes)}"
                else:
                    logger.info(f"⚠️ Автоисправление для '{nickname}' невозможно")
                    notes = "Требуется ручное исправление"

                return NickCheckResult(
                    approve=False,
                    reasons=[error_message],
                    fixed_full=fixed_nick if fixes else None,
                    notes_to_user=notes
                )

        except Exception as e:
            logger.error(f"❌ Критическая ошибка проверки никнейма '{nickname}': {e}")
            return NickCheckResult(
                approve=False,
                reasons=[f"Техническая ошибка: {str(e)}"],
                fixed_full=None,
                notes_to_user="Обратитесь к администратору"
            )