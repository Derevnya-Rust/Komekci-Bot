# Applying the changes to remove the "готово" text from the embed and create a separate message with a button.
import discord
from discord.ext import commands
import logging
import asyncio
import traceback
from datetime import datetime, timezone
import time
import json
from typing import Optional
import re

# Локальный кэш для Steam URL (fallback для replit DB)
local_steam_cache = {}

from cogs.ai import ask_groq
from config import config
from utils.discord_logger import log_error, discord_logger
from utils.logger import get_module_logger

logger = get_module_logger(__name__)
from handlers.novichok import (
    get_account_age_days,
    extract_steam_links,
    extract_steam_links_from_embed,
    check_steam_profile_and_nickname,
    extract_steam_id_from_url,
)
from utils.validators import is_nickname_format_valid, extract_discord_id
from handlers.novichok_actions import TicketActionView
from utils.rate_limiter import safe_send_message
from utils.ai_moderation import decide_nickname
from utils.misc import extract_real_name_from_discord_nick

logger = get_module_logger(__name__)

# Глобальная таблица владельцев заявок: channel_id -> user_id

def build_nick_reject_embed(member, full, reasons, fixed_full):
    """Создаёт embed для отклонённого никнейма"""
    e = discord.Embed(
        title="❌ Никнейм не соответствует правилам",
        description=f"Текущий: **{discord.utils.escape_markdown(full)}**",
        color=0xFF4D4F,
    )
    if reasons:
        e.add_field(name="Причины", value="\n".join(f"• {r}" for r in reasons), inline=False)
    if fixed_full:
        e.add_field(name="Предлагаем исправление", value=f"`{fixed_full}`", inline=False)
        e.set_footer(text="Нажмите «Исправь мой SteamNick | Имя», чтобы применить и перепроверить.")
    else:
        e.set_footer(text="Исправьте ник вручную и нажмите «Проверить заявку ещё раз».")
    return e


def build_nick_ok_embed(full):
    """Создаёт embed для одобренного никнейма"""
    return discord.Embed(
        title="✅ Никнейм соответствует правилам",
        description=f"Текущий: **{discord.utils.escape_markdown(full)}**",
        color=0x52C41A,
    )


class NicknameMismatchModal(discord.ui.Modal):
    """Модальное окно для ручного исправления несовпадающих никнеймов"""

    def __init__(self, user_id: int, steam_nick: str, real_name: str, source_message_id: int = None, channel_id: int = None):
        super().__init__(title="Исправление никнейма", timeout=None)
        self.user_id = user_id
        self.steam_nick = steam_nick
        self.real_name = real_name
        self.source_message_id = source_message_id
        self.channel_id = channel_id

    nickname_input = discord.ui.TextInput(
        label="SteamNick | Имя",
        style=discord.TextStyle.short,
        max_length=32,
        placeholder="Например: Terminator | Володя",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_nick = self.nickname_input.value.strip()

        try:
            await interaction.response.defer(ephemeral=False)

            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.followup.send("❌ Пользователь не найден на сервере.", ephemeral=True)
                return

            # Проверка формата ника
            if ' | ' not in new_nick:
                await interaction.followup.send(
                    "❌ Неправильный формат. Используйте: `SteamNick | Имя`\n"
                    f"Пример: `{self.steam_nick} | {self.real_name}`",
                    ephemeral=True
                )
                return

            # Применяем новый никнейм
            old_nick = member.nick or member.display_name
            await member.edit(nick=new_nick, reason="Ручное исправление никнейма при подаче заявки")

            # Создаем сообщение подтверждения
            success_message = (
                f"✅ **Никнейм изменён вручную!**\n\n"
                f"🔄 **Изменения:**\n"
                f"• Было: `{old_nick}`\n"
                f"• Стало: `{new_nick}`\n\n"
                f"🔄 **Продолжаю обработку заявки...**"
            )

            # Обновляем исходное сообщение
            channel = interaction.client.get_channel(self.channel_id or interaction.channel.id)
            if self.source_message_id and channel:
                try:
                    msg = await channel.fetch_message(self.source_message_id)
                    await msg.edit(content=success_message, view=None)
                except discord.NotFound:
                    await channel.send(success_message)
            else:
                await interaction.followup.send(success_message)

            # Продолжаем обработку заявки
            await asyncio.sleep(3)
            bot = interaction.client
            ticket_handler = bot.get_cog("TicketHandler")
            if ticket_handler and channel:
                await ticket_handler.analyze_and_respond_to_application(channel, member)

            logger.info(f"✅ Никнейм изменён вручную: {old_nick} → {new_nick}")

        except discord.HTTPException as e:
            logger.error(f"❌ Ошибка Discord при изменении никнейма: {e}")
            if "Missing Permissions" in str(e) or "50013" in str(e):
                await interaction.followup.send(
                    "❌ У бота нет прав для изменения никнеймов. Обратитесь к администратору для настройки прав бота.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send("❌ Ошибка при изменении никнейма. Проверьте правильность формата.", ephemeral=True)
        except Exception as e:
            logger.error(f"❌ Ошибка в NicknameMismatchModal: {e}")
            await interaction.followup.send("❌ Произошла ошибка. Попробуйте позже.", ephemeral=True)


class ManualNickFixModal(discord.ui.Modal):
    def __init__(self, user_id: int, source_message_id: int = None, channel_id: int = None):
        super().__init__(title="Исправление никнейма вручную", timeout=None)
        self.user_id = user_id
        self.source_message_id = source_message_id  # FIX: сохраняем ID исходного сообщения
        self.channel_id = channel_id  # FIX: сохраняем ID канала

    nickname_input = discord.ui.TextInput(label="SteamNick | Имя", style=discord.TextStyle.short, max_length=32)

    async def on_submit(self, interaction: discord.Interaction):
        new_nick = self.nickname_input.value.strip()

        try:
            # FIX: prevent Unknown interaction (10062)
            await interaction.response.defer(ephemeral=False)

            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.followup.send(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            # Проверка длины ника
            if len(new_nick) > 32:
                await interaction.followup.send("Ник длиннее 32 символов. Сократите.", ephemeral=True)
                return

            # Применяем исправление
            old_nick = member.nick or member.display_name
            await member.edit(nick=new_nick, reason="Ручное исправление ника (modal)")
            logger.info(f"Ручное изменение ника для {member.id}: {old_nick} -> {new_nick}")

            # Перепроверка после изменения ника через AI
            nick_result = await decide_nickname(new_nick)
            if not nick_result.approve:
                public_reasons = nick_result.public_reasons or []
                fixed_suggestion = nick_result.fixed_full

                view = NicknameRecheckView(member.id, fixed_suggestion)
                nickname_embed = build_nick_reject_embed(
                    member, new_nick, public_reasons, fixed_suggestion
                )

                channel = interaction.client.get_channel(self.channel_id or interaction.channel.id)
                if not channel:
                    try:
                        channel = await interaction.client.fetch_channel(self.channel_id or interaction.channel.id)
                    except:
                        channel = interaction.channel

                if self.source_message_id:
                    try:
                        msg = await channel.fetch_message(self.source_message_id)
                        await msg.edit(embed=nickname_embed, view=view)
                    except discord.NotFound:
                        await channel.send(embed=nickname_embed, view=view)
                else:
                    await channel.send(embed=nickname_embed, view=view)

                await interaction.followup.send("Ник был изменен, но всё ещё не соответствует правилам.", ephemeral=True)
                return

            # Если ник одобрен AI - пингуем модераторов для финального одобрения
            success_embed = discord.Embed(
                title="✅ Никнейм проверен и соответствует правилам",
                description=f"Никнейм **{new_nick}** успешно прошел проверку AI",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            success_embed.add_field(
                name="🔄 Изменения",
                value=f"**Было:** `{member.display_name}`\n**Стало:** `{new_nick}`",
                inline=False,
            )

            success_embed.add_field(
                name="👨‍💼 Требуется одобрение",
                value="<@&1208155641013821460> <@&1208155641013821461> Пожалуйста, проверьте заявку и примите решение.",
                inline=False,
            )

            # Создаем view для принятия/отклонения заявки
            from handlers.novichok_actions import TicketActionView
            approval_view = TicketActionView(member.id, "manual_fix")

            channel = interaction.client.get_channel(self.channel_id or interaction.channel.id)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(self.channel_id or interaction.channel.id)
                except:
                    channel = interaction.channel

            if self.source_message_id:
                try:
                    msg = await channel.fetch_message(self.source_message_id)
                    await msg.edit(embed=success_embed, view=approval_view)
                except discord.NotFound:
                    await channel.send(embed=success_embed, view=approval_view)
            else:
                await channel.send(embed=success_embed, view=approval_view)

            await interaction.followup.send("Ник успешно изменен и передан на одобрение модераторам.", ephemeral=True)

        except Exception as e:
            logger.error(f"❌ Ошибка в on_submit ManualNickFixModal: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при обработке вашего ника. Попробуйте позже.",
                ephemeral=True,
            )


class NicknameRecheckView(discord.ui.View):
    def __init__(
        self,
        user_id: int = None,
        suggested_nick: Optional[str] = None,
        *,
        timeout: float | None = None
    ):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.suggested_nick = suggested_nick

    @discord.ui.button(
        label="✅ Исправь мой SteamNick | Имя",
        style=discord.ButtonStyle.success,
        custom_id="auto_fix_nickname_v2",
    )
    async def auto_fix_nickname(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Автоматическое применение исправления ника"""
        try:
            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.response.send_message(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            if not self.suggested_nick:
                await interaction.response.send_message(
                    "❌ Нет предложенного исправления для никнейма.", ephemeral=True
                )
                return

            # FIX: переименовываем пользователя в fixed_full
            await member.edit(
                nick=self.suggested_nick,
                reason="Автоматическое исправление никнейма по заявке",
            )

            # FIX: отправляем embed "Готово. Запускаю перепроверку..."
            processing_embed = discord.Embed(
                title="✅ Никнейм исправлен!",
                description=f"Ваш никнейм изменён на: **{self.suggested_nick}**\n\n🔄 Запускаю перепроверку...",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )
            await interaction.response.edit_message(embed=processing_embed, view=None)

            # FIX: автоматически запускаем повторную проверку
            await asyncio.sleep(2)  # Небольшая задержка для обновления никнейма

            # Запускаем повторную проверку и если OK, показываем кнопки принять/отказать
            await self.recheck_application_logic(interaction.channel, member)

        except Exception as e:
            logger.error(f"❌ Ошибка автоисправления ника: {e}")
            await interaction.response.send_message(f"Не удалось изменить ник: {e}", ephemeral=True)

    @discord.ui.button(label="Я исправлю сам", style=discord.ButtonStyle.secondary, custom_id="nick_manual_fix_v2")
    async def manual_fix_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Ручное исправление через modal"""
        # FIX: передаём ID исходного сообщения и канала
        modal = ManualNickFixModal(
            self.user_id,
            source_message_id=interaction.message.id,
            channel_id=interaction.channel.id
        )
        await interaction.response.send_modal(modal)

    # Вспомогательная функция для повторной проверки
    async def recheck_application_logic(self, channel, member):
        """Повторно запускает логику проверки заявки"""
        try:
            # Имитируем вызов analyze_and_respond_to_application
            # В реальном коде вам может потребоваться получить доступ к инстансу Cog
            # Для простоты, здесь мы вызываем decide_nickname напрямую
            # FIX: await вызов проверки никнейма
            nick_result = await decide_nickname(member.display_name)
            if not nick_result.approve:  # FIX: обращение как к атрибуту
                public_reasons = nick_result.public_reasons or []  # FIX: обращение как к атрибуту
                fixed_suggestion = nick_result.fixed_full  # FIX: обращение как к атрибуту

                # FIX: зелёная кнопка активна только если есть fixed_full
                view = NicknameRecheckView(member.id, fixed_suggestion)
                nickname_embed = build_nick_reject_embed(
                    member, member.display_name, public_reasons, fixed_suggestion
                )
                await safe_send_message(
                    channel,
                    embed=nickname_embed,
                    view=view
                )
            else:
                # Ник одобрен, показываем кнопки принятия/отклонения
                ok_embed = build_nick_ok_embed(member.display_name)
                # ЗАМЕНИТЕ ApplicationDecisionView на ваш класс View для принятия/отклонения
                # Например, если у вас есть класс TicketDecisionView, используйте его
                # Для примера, используем TicketActionView, но вам нужно будет заменить его на реальный
                from handlers.novichok_actions import TicketActionView
                accept_view = TicketActionView(member.id, "unknown") # <-- ЗАМЕНИТЕ НА ВАШ КЛАСС VIEW
                await safe_send_message(channel, embed=ok_embed, view=accept_view)

        except Exception as e:
            logger.error(f"❌ Ошибка при повторной проверке заявки: {e}")
            await safe_send_message(
                channel,
                f"{member.mention} ⚠️ Произошла ошибка при повторной проверке. Обратитесь к модератору."
            )


class NicknameFixView(discord.ui.View):
    """View для исправления несовпадающих никнеймов"""

    def __init__(self, user_id: int = None, original_nick: str = "", suggested_nick: str = "", steam_nick: str = ""):
        super().__init__(timeout=None)
        self.user_id = user_id or 0
        self.original_nick = original_nick
        self.suggested_nick = suggested_nick
        self.steam_nick = steam_nick

    @discord.ui.button(
        label="✅ Исправить автоматически",
        style=discord.ButtonStyle.success,
        custom_id="auto_fix_steam_nick_v3",
    )
    async def auto_fix_nick(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Автоматическое исправление никнейма"""
        try:
            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
                return

            # Применяем исправленный никнейм
            await member.edit(
                nick=self.suggested_nick,
                reason="Автоматическое исправление никнейма по Steam профилю"
            )

            # Создаем embed подтверждения
            success_embed = discord.Embed(
                title="✅ Никнейм исправлен",
                description=f"Ник игрока **{self.original_nick}** исправлен на **{self.suggested_nick}**",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            success_embed.add_field(
                name="🔄 Изменения",
                value=f"**Было:** `{self.original_nick}`\n**Стало:** `{self.suggested_nick}`",
                inline=False,
            )

            await interaction.response.edit_message(embed=success_embed, view=None)

            # Запускаем повторную проверку заявки
            await asyncio.sleep(2)
            await self._recheck_application(interaction.channel, member)

            logger.info(f"✅ Никнейм автоматически исправлен: {self.original_nick} → {self.suggested_nick}")

        except Exception as e:
            logger.error(f"❌ Ошибка автоисправления никнейма: {e}")
            await interaction.response.send_message("❌ Ошибка исправления никнейма.", ephemeral=True)

    @discord.ui.button(
        label="🔧 Исправлю сам",
        style=discord.ButtonStyle.secondary,
        custom_id="manual_fix_steam_nick_v3",
    )
    async def manual_fix_nick(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Напоминание об исправлении вручную"""
        try:
            manual_embed = discord.Embed(
                title="🔧 Исправьте никнейм вручную",
                description=f"Исправьте свой Discord никнейм на **{self.suggested_nick}** и нажмите кнопку \"Проверить заявку ещё раз\"",
                color=0x0099FF,
            )

            manual_embed.add_field(
                name="📋 Инструкция",
                value="1. Правый клик на свой ник в Discord\n2. Выберите \"Изменить никнейм на сервере\"\n3. Введите новый ник\n4. Нажмите \"Проверить заявку ещё раз\"",
                inline=False,
            )

            await interaction.response.edit_message(embed=manual_embed, view=None)

        except Exception as e:
            logger.error(f"❌ Ошибка напоминания о ручном исправлении: {e}")

    async def _recheck_application(self, channel, member):
        """Перезапускает проверку заявки после исправления ника"""
        try:
            # Получаем TicketHandler
            bot = channel.guild._state._get_client()
            ticket_handler = bot.get_cog("TicketHandler")
            if ticket_handler:
                await ticket_handler.analyze_and_respond_to_application(channel, member)
        except Exception as e:
            logger.error(f"❌ Ошибка повторной проверки: {e}")


class NicknameFixView(discord.ui.View):
    """View для исправления несовпадающих никнеймов"""

    def __init__(self, user_id: int = None, original_nick: str = "", suggested_nick: str = "", steam_nick: str = ""):
        super().__init__(timeout=None)
        self.user_id = user_id or 0
        self.original_nick = original_nick
        self.suggested_nick = suggested_nick
        self.steam_nick = steam_nick

    @discord.ui.button(
        label="✅ Исправить автоматически",
        style=discord.ButtonStyle.success,
        custom_id="auto_fix_steam_nick_v3",
    )
    async def auto_fix_nick(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Автоматическое исправление никнейма"""
        try:
            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
                return

            # Применяем исправленный никнейм
            await member.edit(
                nick=self.suggested_nick,
                reason="Автоматическое исправление никнейма по Steam профилю"
            )

            # Создаем embed подтверждения
            success_embed = discord.Embed(
                title="✅ Никнейм исправлен",
                description=f"Ник игрока **{self.original_nick}** исправлен на **{self.suggested_nick}**",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            success_embed.add_field(
                name="🔄 Изменения",
                value=f"**Было:** `{self.original_nick}`\n**Стало:** `{self.suggested_nick}`",
                inline=False,
            )

            await interaction.response.edit_message(embed=success_embed, view=None)

            # Запускаем повторную проверку заявки
            await asyncio.sleep(2)
            await self._recheck_application(interaction.channel, member)

            logger.info(f"✅ Никнейм автоматически исправлен: {self.original_nick} → {self.suggested_nick}")

        except Exception as e:
            logger.error(f"❌ Ошибка автоисправления никнейма: {e}")
            await interaction.response.send_message("❌ Ошибка исправления никнейма.", ephemeral=True)

    @discord.ui.button(
        label="🔧 Исправлю сам",
        style=discord.ButtonStyle.secondary,
        custom_id="manual_fix_steam_nick_v3",
    )
    async def manual_fix_nick(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Напоминание об исправлении вручную"""
        try:
            manual_embed = discord.Embed(
                title="🔧 Исправьте никнейм вручную",
                description=f"Исправьте свой Discord никнейм на **{self.suggested_nick}** и нажмите кнопку \"Проверить заявку ещё раз\"",
                color=0x0099FF,
            )

            manual_embed.add_field(
                name="📋 Инструкция",
                value="1. Правый клик на свой ник в Discord\n2. Выберите \"Изменить никнейм на сервере\"\n3. Введите новый ник\n4. Нажмите \"Проверить заявку ещё раз\"",
                inline=False,
            )

            await interaction.response.edit_message(embed=manual_embed, view=None)

        except Exception as e:
            logger.error(f"❌ Ошибка напоминания о ручном исправлении: {e}")

    async def _recheck_application(self, channel, member):
        """Перезапускает проверку заявки после исправления ника"""
        try:
            # Получаем TicketHandler
            bot = channel.guild._state._get_client()
            ticket_handler = bot.get_cog("TicketHandler")
            if ticket_handler:
                await ticket_handler.analyze_and_respond_to_application(channel, member)
        except Exception as e:
            logger.error(f"❌ Ошибка повторной проверки: {e}")


class NicknameMismatchFixView(discord.ui.View):
    """View для исправления несовпадающих Discord и Steam никнеймов"""

    def __init__(self, user_id: int = None, discord_nick: str = None, steam_nick: str = None, real_name: str = None):
        super().__init__(timeout=None)
        self.user_id = user_id or 0
        self.discord_nick = discord_nick or ""
        self.steam_nick = steam_nick or ""
        self.real_name = real_name or ""

    @discord.ui.button(
        label="Исправить автоматически",
        style=discord.ButtonStyle.success,
        custom_id="auto_fix_nick_mismatch_v4",
    )
    async def auto_fix_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Автоматическое исправление Discord никнейма на формат SteamNick | Имя"""
        try:
            # Проверяем, не обработано ли уже взаимодействие
            if interaction.response.is_done():
                logger.warning(f"⚠️ Interaction уже обработано для {interaction.user.display_name}")
                return

            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
                return

            # Формируем новый никнейм
            new_nick = f"{self.steam_nick} | {self.real_name}"

            # Проверяем длину ника (Discord лимит 32 символа)
            if len(new_nick) > 32:
                await interaction.response.send_message(
                    f"❌ Предлагаемый никнейм слишком длинный ({len(new_nick)} символов). Максимум 32 символа.",
                    ephemeral=True
                )
                return

            # Сначала отвечаем на interaction, затем меняем ник
            await interaction.response.defer()

            # Применяем исправленный никнейм
            await member.edit(
                nick=new_nick,
                reason="Автоматическое исправление никнейма по Steam профилю"
            )

            # Создаем сообщение подтверждения
            success_message = (
                f"✅ **Никнейм исправлен!**\n\n"
                f"🔄 **Изменения:**\n"
                f"• Было: `{self.discord_nick}`\n"
                f"• Стало: `{new_nick}`\n\n"
                f"🔄 **Запускаю перепроверку заявки...**"
            )

            await interaction.edit_original_response(content=success_message, view=None)

            # Запускаем повторную проверку заявки
            await asyncio.sleep(3)
            await self._recheck_application(interaction.channel, member)

            logger.info(f"✅ Никнейм автоматически исправлен: {self.discord_nick} → {new_nick}")

        except discord.HTTPException as e:
            try:
                if not interaction.response.is_done():
                    if "Invalid Form Body" in str(e):
                        await interaction.response.send_message("❌ Некорректный никнейм. Попробуйте исправить вручную.", ephemeral=True)
                    elif "Missing Permissions" in str(e) or "50013" in str(e):
                        await interaction.response.send_message(
                            "❌ У бота нет прав для изменения никнеймов. Обратитесь к администратору для настройки прав бота или измените никнейм вручную.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message("❌ Ошибка Discord API при изменении никнейма.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Ошибка при изменении никнейма.", ephemeral=True)
            except:
                logger.error(f"❌ Не удалось отправить сообщение об ошибке: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка автоисправления никнейма: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Произошла ошибка. Попробуйте исправить вручную.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Произошла ошибка. Попробуйте исправить вручную.", ephemeral=True)
            except:
                logger.error(f"❌ Не удалось отправить сообщение об ошибке: {e}")

    @discord.ui.button(
        label="Исправлю сам",
        style=discord.ButtonStyle.danger,
        custom_id="manual_fix_nick_mismatch_v4",
    )
    async def manual_fix_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Открывает модальное окно для ручного исправления никнейма"""
        try:
            # Проверяем, не обработано ли уже взаимодействие
            if interaction.response.is_done():
                logger.warning(f"⚠️ Interaction уже обработано для модального окна {interaction.user.display_name}")
                return

            # Создаем модальное окно с подсказкой
            modal = NicknameMismatchModal(
                self.user_id,
                self.steam_nick,
                self.real_name,
                interaction.message.id,
                interaction.channel.id
            )
            await interaction.response.send_modal(modal)

        except discord.HTTPException as e:
            logger.error(f"❌ Ошибка открытия модального окна: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Ошибка открытия формы для ввода никнейма.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Ошибка открытия формы для ввода никнейма.", ephemeral=True)
            except:
                pass
        except Exception as e:
            logger.error(f"❌ Ошибка открытия модального окна: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Ошибка открытия формы для ввода никнейма.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Ошибка открытия формы для ввода никнейма.", ephemeral=True)
            except:
                pass

    async def _recheck_application(self, channel, member):
        """Перезапускает проверку заявки после исправления ника"""
        try:
            # Получаем TicketHandler
            bot = channel.guild._state._get_client()
            ticket_handler = bot.get_cog("TicketHandler")
            if ticket_handler:
                await ticket_handler.analyze_and_respond_to_application(channel, member)
        except Exception as e:
            logger.error(f"❌ Ошибка повторной проверки: {e}")
            await safe_send_message(
                channel,
                f"{member.mention} ⚠️ Произошла ошибка при повторной проверке заявки. Обратитесь к модератору."
            )


class TicketHandler(commands.Cog):
    """Обработчик тикетов заявок"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._welcomed_channels = set()

    async def process_new_ticket(self, channel, user):
        """Обработка нового тикета"""
        try:
            if channel.id not in self._welcomed_channels:
                # Отправляем приветствие
                await safe_send_message(
                    channel,
                    f"👋 Добро пожаловать, {user.mention}! Ваша заявка принята к рассмотрению.\n"
                    f"🔍 Сейчас проверим ваш Steam-профиль и никнейм..."
                )
                self._welcomed_channels.add(channel.id)
                logger.info(f"✅ Отправлено приветствие в {channel.name}")

            # Запускаем анализ заявки
            await self.analyze_and_respond_to_application(channel, user)
        except Exception as e:
            logger.error(f"❌ Ошибка обработки нового тикета: {e}")

    async def analyze_and_respond_to_application(self, channel, user):
        """Анализ и ответ на заявку"""
        try:
            await safe_send_message(
                channel,
                f"🔍 Запущен анализ вашей заявки...\n"
                f"⏰ Проверяю Steam-профиль и никнейм..."
            )

            # Получаем данные пользователя
            member = channel.guild.get_member(user.id)
            if not member:
                logger.warning(f"Пользователь {user.id} не найден на сервере.")
                return

            # Получаем Discord ник
            discord_nick = member.nick or member.display_name

            # Ищем Steam ссылки в истории канала
            steam_profile_url = None
            steam_id64 = None
            steam_nick = None

            # Проверяем сообщения в канале для поиска Steam ссылок
            async for message in channel.history(limit=20):
                if message.embeds:
                    for embed in message.embeds:
                        if embed.fields:
                            for field in embed.fields:
                                if field.value and "steamcommunity.com" in field.value:
                                    from handlers.novichok import extract_steam_links
                                    steam_links = extract_steam_links(field.value)
                                    if steam_links:
                                        steam_profile_url = steam_links[0]
                                        break
                        if steam_profile_url:
                            break
                if steam_profile_url:
                    break

            if not steam_profile_url:
                await safe_send_message(
                    channel,
                    f"❌ Не удалось найти Steam профиль в заявке. Пожалуйста, убедитесь, что указали корректную ссылку на Steam профиль."
                )
                return

            # Получаем SteamID64 и данные профиля
            from handlers.steam_api import get_steam_id64, steam_client

            steam_id64 = await get_steam_id64(steam_profile_url)
            if steam_id64:
                steam_data = await steam_client.get_player_summary(steam_id64)
                if steam_data and steam_data.get("success"):
                    steam_nick = steam_data.get("personaname", "")

            # Проверяем совпадение Discord ника и Steam ника
            nick_match = False
            if discord_nick and steam_nick:
                # Убираем возможные префиксы и сравниваем основную часть ника
                discord_left = discord_nick.split(' | ')[0].strip() if ' | ' in discord_nick else discord_nick.strip()
                steam_nick_clean = steam_nick.strip()

                # Проверяем точное совпадение
                if discord_left.lower() == steam_nick_clean.lower():
                    nick_match = True
                else:
                    # Проверяем совпадение с учетом клановых приставок (VLG., [VLG], etc.)
                    # Убираем клановые приставки из Steam ника
                    steam_without_clan = re.sub(r'^(VLG\.|VLG_|\[VLG\]|VLG)', '', steam_nick_clean, flags=re.IGNORECASE).strip()
                    discord_without_clan = re.sub(r'^(VLG\.|VLG_|\[VLG\]|VLG)', '', discord_left, flags=re.IGNORECASE).strip()

                    # Проверяем совпадение без клановых приставок
                    if discord_without_clan.lower() == steam_without_clan.lower():
                        nick_match = True
                        logger.info(f"✅ Ники совпадают после удаления клановых приставок: '{discord_without_clan}' == '{steam_without_clan}'")
                    else:
                        # Дополнительная проверка на схожесть (учитываем опечатки)
                        from difflib import SequenceMatcher
                        similarity = SequenceMatcher(None, discord_without_clan.lower(), steam_without_clan.lower()).ratio()
                        if similarity >= 0.85:  # 85% схожести
                            nick_match = True
                            logger.info(f"✅ Ники схожи после удаления клановых приставок: '{discord_without_clan}' ~ '{steam_without_clan}' (схожесть: {similarity:.2f})")

            if not nick_match and discord_nick and steam_nick:
                # Никнеймы не совпадают, отправляем специальное сообщение
                from utils.misc import extract_real_name_from_discord_nick
                real_name = extract_real_name_from_discord_nick(discord_nick)

                if not real_name:
                    # Пытаемся извлечь имя из правой части ника Discord
                    if ' | ' in discord_nick:
                        real_name = discord_nick.split(' | ', 1)[1].strip()
                    else:
                        real_name = "Ваше имя"  # fallback

                # Проверяем, нужно ли включить детальное логирование
                if getattr(config, "DEBUG_NICKNAME_CHECKS", False):
                    # Вычисляем очищенные варианты для логирования
                    discord_left = discord_nick.split(' | ')[0].strip() if ' | ' in discord_nick else discord_nick.strip()
                    steam_nick_clean = steam_nick.strip()
                    
                    # Убираем клановые приставки
                    import re
                    steam_without_clan = re.sub(r'^(VLG\.|VLG_|\[VLG\]|VLG)', '', steam_nick_clean, flags=re.IGNORECASE).strip()
                    discord_without_clan = re.sub(r'^(VLG\.|VLG_|\[VLG\]|VLG)', '', discord_left, flags=re.IGNORECASE).strip()
                    
                    logger.info(f"🔍 DEBUG: Детальная проверка совпадения ников:")
                    logger.info(f"   Исходный Discord ник: '{discord_nick}'")
                    logger.info(f"   Исходный Steam ник: '{steam_nick}'")
                    logger.info(f"   Discord левая часть: '{discord_left}'")
                    logger.info(f"   Steam очищенный: '{steam_nick_clean}'")
                    logger.info(f"   Discord без клана: '{discord_without_clan}'")
                    logger.info(f"   Steam без клана: '{steam_without_clan}'")
                    logger.info(f"   Точное совпадение: {discord_left.lower() == steam_nick_clean.lower()}")
                    logger.info(f"   Совпадение без клана: {discord_without_clan.lower() == steam_without_clan.lower()}")
                    
                    # Проверка схожести
                    from difflib import SequenceMatcher
                    similarity = SequenceMatcher(None, discord_without_clan.lower(), steam_without_clan.lower()).ratio()
                    logger.info(f"   Схожесть (0.0-1.0): {similarity:.3f}")
                    logger.info(f"   Итоговое решение nick_match: {nick_match}")

                if discord_name_clean != steam_name_clean:
                    logger.warning(f"❌ Ники не совпадают для {user.display_name}")

                    # Отправляем кастомное сообщение о несовпадении ников
                    mismatch_embed = discord.Embed(
                        title="❌ Никнейм не соответствует Steam профилю",
                        description=(
                            f"**Ваш Discord ник:** `{discord_nick}`\n"
                            f"**Ваш Steam ник:** `{steam_nick}`\n\n"
                            "**Требования:**\n"
                            "• Discord ник должен быть в формате: `SteamNick | Имя`\n"
                            "• SteamNick должен совпадать с вашим ником в Steam\n"
                            "• Имя должно быть на кириллице с заглавной буквы"
                        ),
                        color=0xFF0000
                    )

                    mismatch_embed.add_field(
                        name="🔧 Как исправить:",
                        value=(
                            "1. Нажмите на свой ник в Discord\n"
                            "2. Выберите \"Изменить никнейм на сервере\"\n"
                            f"3. Введите: `{steam_nick} | ВашеИмя`\n"
                            "4. Нажмите кнопку \"Перепроверить\" ниже"
                        ),
                        inline=False
                    )

                    view = NicknameMismatchFixView(user.id, discord_nick, steam_nick, "")
                    await safe_send_message(channel, embed=mismatch_embed, view=view)

                    # ВАЖНО: возвращаемся, чтобы не продолжать проверку через AI
                    return


            # Проверяем формат Discord никнейма (БАЗОВАЯ ПРОВЕРКА СНАЧАЛА)
            await asyncio.sleep(2)

            current_nick = user.nick or user.display_name
            logger.info(f"🔍 Проверяю формат никнейма: {current_nick}")

            # КРИТИЧЕСКИ ВАЖНО: Сначала базовые проверки формата
            if " | " not in current_nick:
                nickname_embed = discord.Embed(
                    title="❌ Неправильный формат никнейма",
                    description=f"**Ваш никнейм:** `{current_nick}`\n\n**Требуется формат:** `SteamNick | Имя`",
                    color=0xFF0000
                )
                nickname_embed.add_field(
                    name="📋 Как исправить:",
                    value="1. Правый клик на свой ник в Discord\n2. Выберите \"Изменить никнейм на сервере\"\n3. Введите ник в формате: `SteamNick | Имя`",
                    inline=False
                )
                
                await safe_send_message(channel, embed=nickname_embed)
                logger.warning(f"❌ Никнейм '{current_nick}' не содержит разделителя ' | '")
                return

            parts = current_nick.split(" | ")
            if len(parts) != 2:
                # КРИТИЧЕСКАЯ ОШИБКА: два или более разделителей " | "
                steam_part = parts[0] if parts else ""
                
                # Попытка угадать правильное имя из последней части
                suggested_name = parts[-1] if len(parts) > 1 else "Ваше_Имя"
                suggested_nick = f"{steam_part} | {suggested_name}" if steam_part else f"SteamNick | {suggested_name}"
                
                nickname_embed = discord.Embed(
                    title="❌ Неправильный формат никнейма",
                    description=(
                        f"**Ваш никнейм:** `{current_nick}`\n\n"
                        f"**Проблема:** Найдено {len(parts)-1} разделителей \" | \", должен быть только один\n\n"
                        f"**Требуется формат:** `SteamNick | Имя`"
                    ),
                    color=0xFF0000
                )
                
                nickname_embed.add_field(
                    name="🔧 Предлагаемое исправление:",
                    value=f"`{suggested_nick}`",
                    inline=False
                )
                
                nickname_embed.add_field(
                    name="📋 Как исправить:",
                    value="1. Нажмите кнопку \"Исправить автоматически\" ниже\n2. Или исправьте вручную: ПКМ на ник → \"Изменить никнейм на сервере\"",
                    inline=False
                )
                
                view = NicknameRecheckView(user.id, suggested_nick)
                await safe_send_message(channel, embed=nickname_embed, view=view)
                
                logger.warning(f"❌ Никнейм '{current_nick}' содержит {len(parts)-1} разделителей, ожидался 1")
                return

            # Если базовый формат правильный, проверяем через AI модерацию
            try:
                from utils.ai_moderation import decide_nickname
                nick_result = await decide_nickname(current_nick)

                if not nick_result.approve:
                    # Никнейм не соответствует правилам - отправляем сообщение с исправлением
                    public_reasons = nick_result.public_reasons or []
                    fixed_suggestion = nick_result.fixed_full

                    view = NicknameRecheckView(user.id, fixed_suggestion)
                    nickname_embed = build_nick_reject_embed(
                        user, current_nick, public_reasons, fixed_suggestion
                    )

                    await safe_send_message(
                        channel,
                        embed=nickname_embed,
                        view=view
                    )

                    logger.info(f"⚠️ Никнейм отклонен AI: {current_nick} - {', '.join(public_reasons)}")
                    return # Останавливаем дальнейшую обработку

            except Exception as e:
                logger.error(f"❌ Ошибка проверки никнейма через AI: {e}")
                # Продолжаем обработку при ошибке AI

            await safe_send_message(
                channel,
                f"✅ Анализ завершён! Ожидайте решения модератора."
            )

            # Создаем embed с результатами анализа и кнопки принятия/отклонения
            result_embed = discord.Embed(
                title="✅ Анализ заявки завершён",
                description=f"Заявка пользователя {user.display_name} готова к рассмотрению",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )
            result_embed.add_field(
                name="👤 Заявитель",
                value=f"{user.display_name}\nID: `{user.id}`",
                inline=True
            )
            result_embed.add_field(
                name="📊 Статус",
                value="Ожидает решения модератора",
                inline=True
            )
            result_embed.set_footer(text="Модераторы могут принять или отклонить заявку")

            # Импортируем и создаем кнопки решения
            # from handlers.novichok_actions import TicketActionView # Уже импортировано выше
            decision_view = TicketActionView(user.id, channel.id) # Передаем channel.id для дальнейшего использования

            await safe_send_message(
                channel,
                embed=result_embed,
                view=decision_view
            )

            logger.info(f"✅ Анализ заявки завершён для {user.display_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка анализа заявки: {e}\n{traceback.format_exc()}")
            await safe_send_message(
                channel,
                f"❌ Произошла ошибка при анализе заявки. Обратитесь к модератору."
            )
            # Логирование ошибки с трассировкой
            await log_error(e, traceback.format_exc())


async def setup(bot):
    """Настройка cog для tickets"""
    # Регистрируем persistent views
    bot.add_view(NicknameFixView(0, "", "", ""))
    bot.add_view(NicknameRecheckView(0, None))
    bot.add_view(NicknameMismatchFixView(0, "", "", ""))
    logger.info("✅ Persistent views зарегистрированы в tickets.py")

    await bot.add_cog(TicketHandler(bot))