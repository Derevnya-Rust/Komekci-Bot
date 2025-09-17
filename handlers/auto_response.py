
import discord
from discord.ext import commands
import logging
import re
import asyncio
from datetime import datetime, timezone
from utils.rate_limiter import safe_send_message
from config import config
from utils.discord_logger import log_to_channel, log_error, discord_logger
from utils.logger import get_module_logger

logger = get_module_logger(__name__)


class AutoResponseHandler:
    def __init__(self, bot):
        self.bot = bot
        self.response_cooldowns = {}  # Кулдауны для предотвращения спама

    async def handle_message(self, message: discord.Message):
        """Обработка автоматических ответов"""
        try:
            # Игнорируем сообщения от ботов
            if message.author.bot:
                return

            # Игнорируем системные сообщения
            if message.type != discord.MessageType.default:
                return

            # Игнорируем AI канал
            if message.channel.id == 1178436876244361388:
                return

            # Проверяем кулдаун
            user_id = message.author.id
            current_time = asyncio.get_event_loop().time()

            if user_id in self.response_cooldowns:
                if (
                    current_time - self.response_cooldowns[user_id] < 30
                ):  # 30 секунд кулдаун
                    return

            # Обрабатываем автоответы только в тикет-каналах
            if not (
                hasattr(message.channel, "name")
                and message.channel.name.startswith("new_")
            ):
                return

            content = message.content.lower().strip()

            # Проверяем триггеры автоответов для перепроверки
            recheck_triggers = [
                "готово",
                "готов",
                "проверь",
                "проверь заявку",
                "исправил",
                "исправила",
                "исправлено",
            ]
            if any(trigger in content for trigger in recheck_triggers):
                await self._send_recheck_response(message)
                self.response_cooldowns[user_id] = current_time

        except Exception as e:
            logger.error(f"Ошибка обработки автоответа: {e}")

    async def _send_recheck_response(self, message: discord.Message):
        """Отправляет ответ о перепроверке заявки"""
        try:
            await safe_send_message(
                message.channel,
                f"🔄 {message.author.mention} Запускаю перепроверку вашей заявки...",
            )

            # Запускаем перепроверку через TicketHandler
            ticket_handler = self.bot.get_cog("TicketHandler")
            if ticket_handler and hasattr(ticket_handler, 'analyze_and_respond_to_application'):
                await ticket_handler.analyze_and_respond_to_application(
                    message.channel, message.author
                )

        except Exception as e:
            logger.error(f"Ошибка отправки автоответа: {e}")


# Глобальный экземпляр обработчика автоответов
auto_response_handler = None


def set_bot(bot):
    """Установить бот для обработчика автоответов"""
    global auto_response_handler
    auto_response_handler = AutoResponseHandler(bot)
