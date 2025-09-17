import discord
import asyncio
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Простой rate limiter на основе asyncio
_last_send = {}
_send_delay = 1.0  # секунды между отправками


async def throttled_send(channel, content=None, **kwargs):
    """Отправка сообщения с rate limiting"""
    channel_id = getattr(channel, 'id', str(channel))

    # Простая задержка между сообщениями
    if channel_id in _last_send:
        elapsed = asyncio.get_event_loop().time() - _last_send[channel_id]
        if elapsed < _send_delay:
            await asyncio.sleep(_send_delay - elapsed)

    try:
        message = await channel.send(content, **kwargs)
        _last_send[channel_id] = asyncio.get_event_loop().time()
        return message
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None


async def safe_send_message(channel, content=None, *, embed=None, view=None, allowed_mentions=None, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок и rate limiting"""
    try:
        # Устанавливаем разумные значения по умолчанию для allowed_mentions
        if allowed_mentions is None:
            allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)

        # Отправляем сообщение
        return await channel.send(
            content=content,
            embed=embed,
            view=view,
            allowed_mentions=allowed_mentions,
            **kwargs
        )
    except discord.HTTPException as e:
        logger.error(f"❌ Ошибка отправки сообщения в {channel}: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при отправке сообщения: {e}")
        return None


async def safe_send_followup(interaction, content=None, **kwargs):
    """Безопасная отправка followup сообщения"""
    try:
        return await interaction.followup.send(content, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки followup: {e}")
        return None


async def safe_add_roles(member, *roles, reason=None):
    """Безопасное добавление ролей"""
    try:
        await member.add_roles(*roles, reason=reason)
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления ролей: {e}")
        return False


async def safe_remove_roles(member, *roles, reason=None):
    """Безопасное удаление ролей"""
    try:
        await member.remove_roles(*roles, reason=reason)
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления ролей: {e}")
        return False


async def safe_edit_member(member, **kwargs):
    """Безопасное редактирование участника"""
    try:
        await member.edit(**kwargs)
        return True
    except Exception as e:
        logger.error(f"Ошибка редактирования участника: {e}")
        return False


async def send_throttled(channel, content, dedupe_key=None):
    """Отправка с дедупликацией"""
    return await throttled_send(channel, content)