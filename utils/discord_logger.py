import discord
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from config import config

logger = logging.getLogger(__name__)


class DiscordLogger:
    """Простой Discord логгер без сложных функций"""

    def __init__(self):
        self.bot = None

    def set_bot(self, bot):
        """Установить экземпляр бота"""
        self.bot = bot

    def info(self, message: str):
        """Логирование информационного сообщения"""
        logger.info(message)

    def error(self, message: str):
        """Логирование ошибки"""
        logger.error(message)


# Глобальный экземпляр Discord логгера
discord_logger = DiscordLogger()


async def log_to_channel(event_type: str, message: str, user=None, channel=None):
    """Упрощенное логирование в канал"""
    try:
        if discord_logger.bot and discord_logger.bot.is_ready():
            log_channel = discord_logger.bot.get_channel(config.LOG_CHANNEL_ID)
            if log_channel and isinstance(log_channel, discord.TextChannel):
                timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                log_message = f"`{timestamp}` **{event_type}** | {message}"
                await log_channel.send(log_message[:2000])
    except Exception as e:
        logger.debug(f"Ошибка отправки лога в Discord: {e}")


async def log_error(error: Exception, context: str = ""):
    """Логирование ошибки"""
    error_message = f"❌ Ошибка: {str(error)}"
    if context:
        error_message += f" | Контекст: {context}"

    logger.error(error_message)
    await log_to_channel("Ошибка", error_message)