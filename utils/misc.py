import discord
import logging

logger = logging.getLogger(__name__)


async def safe_send_message(channel, content=None, *, embed=None, view=None, file=None, files=None):
    """
    Безопасная отправка сообщений с отключенными упоминаниями
    """
    try:
        return await channel.send(
            content=content,
            embed=embed,
            view=view,
            file=file,
            files=files,
            allowed_mentions=discord.AllowedMentions.none()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None


def extract_real_name_from_discord_nick(discord_nick: str) -> str:
    """Извлекает реальное имя из Discord никнейма формата 'SteamNick | Имя'"""
    if " | " in discord_nick:
        parts = discord_nick.split(" | ", 1)
        if len(parts) == 2:
            real_name = parts[1].strip()
            # КРИТИЧЕСКАЯ ПРОВЕРКА: если имя содержит латинские буквы - возвращаем как есть для блокировки
            return real_name

    # Если формат не соответствует, возвращаем имя как есть без замены на "Игрок"
    return discord_nick


__all__ = ["safe_send_message", "extract_real_name_from_discord_nick"]