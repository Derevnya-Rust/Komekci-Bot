# 1. Updated imports and removed legacy Steam API calls, integrated ticket context for hours.

# Imports and setup for the application system cog, focusing on ticket context and Rust hours.
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional
import re
import random

from config import config
from utils.rate_limiter import safe_send_message
from utils.validators import auto_fix_nickname
from utils.discord_logger import log_error, log_to_channel
from utils.ticket_context import TicketContext, get_ctx # Import get_ctx and TicketContext
from utils.ai_moderation import decide_nickname # Import decide_nickname
from utils.nickname_moderator import NicknameModerator
from utils.decision import NickCheckResult
from utils.logger import get_module_logger

# Import SequenceMatcher and define helper function
from difflib import SequenceMatcher

def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()  # 0.0..1.0

logger = get_module_logger(__name__)

# Константы из конфигурации
ADMIN_ROLES = config.ADMIN_ROLES
NEWBIE_ROLE_ID = config.NEWBIE_ROLE_ID
GUEST_ROLE_ID = config.GUEST_ROLE_ID
LOG_CHANNEL_ID = config.LOG_CHANNEL_ID


class AutoFixConfirmationView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        original_nickname: str,
        fixed_nickname: str,
        fixes_applied: list,
    ):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.original_nickname = original_nickname
        self.fixed_nickname = fixed_nickname
        self.fixes_applied = fixes_applied

    @discord.ui.button(
        label="✅ Применить исправления и одобрить", style=discord.ButtonStyle.success
    )
    async def confirm_auto_fix(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Применяет автоисправления и одобряет заявку"""
        try:
            # Получаем пользователя
            user = await interaction.guild.fetch_member(self.user_id)
            if not user:
                await interaction.response.send_message(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            # Применяем исправленный никнейм
            try:
                await user.edit(nick=self.fixed_nickname)
                logger.info(
                    f"🔧 Никнейм автоматически исправлен: {self.original_nickname} → {self.fixed_nickname}"
                )
            except discord.Forbidden:
                logger.warning(
                    f"⚠️ Нет прав для изменения никнейма пользователя {user.display_name}"
                )
            except Exception as nick_error:
                logger.error(f"❌ Ошибка изменения никнейма: {nick_error}")

            # Выдаем роль Новичок
            novichok_role = discord.utils.get(
                interaction.guild.roles, id=1257813489595191296
            )
            if novichok_role and novichok_role not in user.roles:
                await user.add_roles(novichok_role)
                logger.info(
                    f"✅ Роль 'Новичок' выдана пользователю {user.display_name}"
                )

            # Отправляем уведомление пользователю об автоисправлении
            try:
                user_embed = discord.Embed(
                    title="🎉 Поздравляем! Ваша заявка одобрена!",
                    description="Добро пожаловать в Деревню VLG!",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )

                user_embed.add_field(
                    name="🔧 Ваш никнейм был автоматически исправлен",
                    value=f"**Было:** `{self.original_nickname}`\n**Стало:** `{self.fixed_nickname}`\n\n**Примененные исправления:**\n• "
                    + "\n• ".join(self.fixes_applied),
                    inline=False,
                )

                user_embed.add_field(
                    name="📋 Что дальше?",
                    value="• Вам выдана роль **Новичок**\n• Изучите правила сервера\n• Добро пожаловать в сообщество!\n• Ваш никнейм теперь соответствует стандартам Деревни",
                    inline=False,
                )

                user_embed.add_field(
                    name="💡 Почему исправлен никнейм?",
                    value="Никнеймы должны соответствовать формату `Игровойник | Имя` с правильными пробелами и заглавными буквами в имени.",
                    inline=False,
                )

                user_embed.set_footer(
                    text="Деревня VLG • Рады видеть вас в нашем сообществе!"
                )

                await user.send(embed=user_embed)
                logger.info(
                    f"📧 Уведомление об автоисправлении и одобрении отправлено пользователю {user.display_name}"
                )
            except discord.Forbidden:
                logger.warning(
                    f"⚠️ Не удалось отправить ЛС пользователю {user.display_name} (закрыты ЛС)"
                )
            except Exception as dm_error:
                logger.error(f"❌ Ошибка отправки ЛС: {dm_error}")

            # Создаем embed для одобрения в тикете
            approval_embed = discord.Embed(
                title="✅ Заявка одобрена с автоисправлением",
                description=f"Пользователь {user.mention} принят в Деревню VLG!",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            approval_embed.add_field(
                name="🔧 Автоисправления никнейма",
                value=f"**Исправлено:** `{self.original_nickname}` → `{self.fixed_nickname}`\n**Применены исправления:**\n• "
                + "\n• ".join(self.fixes_applied),
                inline=False,
            )

            approval_embed.add_field(
                name="👤 Новый участник",
                value=f"**Участник:** {user.mention}\n**Ник:** `{self.fixed_nickname}`\n**Роль:** Новичок\n**Уведомление:** Отправлено в ЛС",
                inline=False,
            )

            approval_embed.set_footer(
                text=f"Одобрено модератором {interaction.user.display_name}"
            )

            await interaction.response.edit_message(embed=approval_embed, view=None)

        except Exception as e:
            logger.error(f"❌ Ошибка автоисправления и одобрения: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при обработке заявки.", ephemeral=True
            )

    @discord.ui.button(
        label="❌ Отклонить без исправлений", style=discord.ButtonStyle.danger
    )
    async def reject_auto_fix(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отклоняет заявку без применения автоисправлений"""
        try:
            user = await interaction.guild.fetch_member(self.user_id)
            if not user:
                await interaction.response.send_message(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            # Отправляем уведомление пользователю об отклонении
            try:
                user_reject_embed = discord.Embed(
                    title="❌ Заявка отклонена",
                    description="К сожалению, ваша заявка в Деревню VLG была отклонена.",
                    color=0xFF0000,
                    timestamp=datetime.now(timezone.utc),
                )

                user_reject_embed.add_field(
                    name="📝 Причина отклонения",
                    value=f"Ваш никнейм `{self.original_nickname}` не соответствует стандартам сервера и требует ручного исправления.",
                    inline=False,
                )

                user_reject_embed.add_field(
                    name="🔧 Рекомендованные исправления",
                    value="• "
                    + "\n• ".join(self.fixes_applied)
                    + f"\n\n**Исправленный вариант:** `{self.fixed_nickname}`",
                    inline=False,
                )

                user_reject_embed.add_field(
                    name="💡 Что делать дальше?",
                    value="1. Исправьте свой никнейм в Discord\n2. Подайте заявку заново\n3. Убедитесь что формат: `Игровойник | Имя`",
                    inline=False,
                )

                user_reject_embed.set_footer(
                    text="Деревня VLG • Исправьте никнейм и попробуйте снова"
                )

                await user.send(embed=user_reject_embed)
                logger.info(
                    f"📧 Уведомление об отклонении отправлено пользователю {user.display_name}"
                )
            except discord.Forbidden:
                logger.warning(
                    f"⚠️ Не удалось отправить ЛС пользователю {user.display_name} (закрыты ЛС)"
                )
            except Exception as dm_error:
                logger.error(f"❌ Ошибка отправки ЛС: {dm_error}")

            # Создаем embed для отклонения в тикете
            rejection_embed = discord.Embed(
                title="❌ Заявка отклонена",
                description=f"Заявка пользователя {user.mention} отклонена без применения автоисправлений.",
                color=0xFF0000,
                timestamp=datetime.now(timezone.utc),
            )

            rejection_embed.add_field(
                name="📝 Причина отклонения",
                value="Модератор решил не применять автоматические исправления никнейма. Пользователь должен исправить никнейм самостоятельно.",
                inline=False,
            )

            rejection_embed.add_field(
                name="🔧 Возможные исправления",
                value="• "
                + "\n• ".join(self.fixes_applied)
                + f"\n\n**Рекомендованный никнейм:** `{self.fixed_nickname}`",
                inline=False,
            )

            rejection_embed.set_footer(
                text=f"Отклонено модератором {interaction.user.display_name}"
            )

            await interaction.response.edit_message(embed=rejection_embed, view=None)

        except Exception as e:
            logger.error(f"❌ Ошибка отклонения заявки: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при обработке заявки.", ephemeral=True
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем, что только автор может взаимодействовать с кнопками"""
        if interaction.user.id != self.user_id:
            try:
                await interaction.response.send_message(
                    "❌ Только автор заявки может использовать эти кнопки.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                logger.warning(
                    f"⚠️ Interaction истек при проверке прав для {interaction.user.display_name}"
                )
            return False
        return True


class TicketActionView(discord.ui.View):
    def __init__(self, user_id: int = None, steam_url: str = None):
        super().__init__(timeout=None)
        self.user_id = user_id or 0
        self.steam_url = steam_url or "unknown"

    async def find_user_application_data(self, guild, user):
        """Ищет данные заявки пользователя в тикет-каналах (аналогично команде /role)"""
        application_data = {
            "steam_url": "Не указано",
            "rust_hours": "Не указано",
            "how_found": "Не указано",
        }

        try:
            # Ищем тикет-канал пользователя (каналы начинающиеся с "new_")
            for channel in guild.channels:
                if (
                    hasattr(channel, "name")
                    and channel.name.startswith("new_")
                    and isinstance(channel, (discord.TextChannel, discord.Thread))
                ):

                    # Проверяем, есть ли пользователь в названии канала или в истории
                    channel_name_lower = channel.name.lower()
                    user_name_parts = [
                        user.name.lower(),
                        user.display_name.lower().replace(" ", "-"),
                        user.display_name.lower().replace(" ", "_"),
                    ]

                    # Проверяем, содержит ли название канала имя пользователя
                    if any(
                        part in channel_name_lower for part in user_name_parts if part
                    ):
                        logger.info(f"🔍 Найден возможный тикет-канал: {channel.name}")

                        # Проверяем, принадлежит ли канал этому пользователю
                        owner_id = get_ticket_owner(channel.id)
                        if owner_id == user.id:
                            # Ищем embed заявки в этом канале
                            try:
                                async for message in channel.history(limit=30):
                                    if message.embeds and message.author.bot:
                                        for embed in message.embeds:
                                            if (
                                                embed.description
                                                and str(user.id) in embed.description
                                            ):
                                                from handlers.novichok import (
                                                    extract_steam_links,
                                                )

                                                if embed.fields:
                                                    for field in embed.fields:
                                                        if (
                                                            field.value
                                                            and "steamcommunity.com"
                                                            in field.value
                                                        ):
                                                            steam_links = (
                                                                extract_steam_links(
                                                                    field.value
                                                                )
                                                            )
                                                            if steam_links:
                                                                application_data[
                                                                    "steam_url"
                                                                ] = steam_links[0]
                                                                return application_data
                            except Exception as e:
                                logger.error(f"Ошибка поиска в канале {channel.name}: {e}")
                                continue

        except Exception as e:
            logger.error(f"Ошибка поиска данных заявки для {user.display_name}: {e}")

        return application_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем права модератора"""
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id

        if not any(role in user_roles for role in admin_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для управления заявками.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="✅ Принять",
        style=discord.ButtonStyle.success,
        custom_id="accept_application",
    )
    async def accept_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Принятие заявки"""
        await interaction.response.defer()

        try:
            guild = interaction.guild
            user = guild.get_member(self.user_id)

            if not user:
                await interaction.followup.send(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            # Удаляем роль Прохожий и добавляем роль Новичок (как в команде /role)
            guest_role = guild.get_role(GUEST_ROLE_ID)
            newbie_role = guild.get_role(NEWBIE_ROLE_ID)

            # Проверяем что роли существуют
            if not newbie_role:
                await interaction.followup.send(
                    "❌ Роль 'Новичок' не найдена на сервере.", ephemeral=True
                )
                logger.error(f"❌ Роль Новичок (ID: {NEWBIE_ROLE_ID}) не найдена")
                return

            # Сначала удаляем роль Прохожий если есть
            if guest_role and guest_role in user.roles:
                try:
                    await user.remove_roles(
                        guest_role,
                        reason=f"Заявка принята, удаление роли Прохожий модератором {interaction.user.display_name}",
                    )
                    logger.info(f"✅ Удалена роль Прохожий у {user.display_name}")
                except Exception as e:
                    logger.error(
                        f"❌ Ошибка удаления роли Прохожий у {user.display_name}: {e}"
                    )

            # Удаляем роль Новичок если есть (на случай повторного нажатия)
            if newbie_role in user.roles:
                try:
                    await user.remove_roles(
                        newbie_role,
                        reason=f"Очистка перед повторной выдачей роли Новичок",
                    )
                    logger.info(
                        f"🔄 Удалена существующая роль Новичок у {user.display_name}"
                    )
                except Exception as e:
                    logger.error(
                        f"❌ Ошибка удаления существующей роли Новичок у {user.display_name}: {e}"
                    )

            # Проверяем никнейм перед выдачей роли
            current_nick = user.nick or user.display_name
            logger.info(f"🔍 Проверяю никнейм перед выдачей роли: {current_nick}")

            try:
                nick_decision: NickCheckResult = await NicknameModerator.check_nickname(user, current_nick)
                logger.info(f"📋 Результат проверки никнейма: {nick_decision}")

                if not nick_decision.approve:
                    logger.warning(f"🚫 Никнейм отклонен: {', '.join(nick_decision.reasons)}")
                    await log_to_channel(
                        "Moderation",
                        f"Никнейм отклонен при выдаче роли: {current_nick} - {', '.join(nick_decision.reasons)}",
                        user=user,
                        channel=interaction.channel
                    )

                    # Отправляем ephemeral ответ с причинами
                    reject_message = f"❌ **Никнейм не соответствует правилам**\n\n"
                    reject_message += f"**Причины отклонения:**\n"
                    for reason in nick_decision.reasons:
                        reject_message += f"• {reason}\n"

                    if nick_decision.fixed_full:
                        reject_message += f"\n**Пример исправления:** `{nick_decision.fixed_full}`\n"

                    reject_message += f"\n{nick_decision.notes_to_user}"

                    await interaction.followup.send(reject_message, ephemeral=True)
                    return
                else:
                    logger.info(f"✅ Никнейм одобрен: {current_nick}")

            except Exception as e:
                logger.error(f"❌ Ошибка проверки никнейма: {e}")
                await interaction.followup.send(
                    "❌ Ошибка при проверке никнейма. Обратитесь к администрации.", ephemeral=True
                )
                return

            # Добавляем роль Новичок
            try:
                await user.add_roles(
                    newbie_role,
                    reason=f"Заявка принята модератором {interaction.user.display_name}",
                )
                logger.info(f"✅ Выдана роль Новичок пользователю {user.display_name}")
            except Exception as e:
                logger.error(
                    f"❌ Ошибка выдачи роли Новичок пользователю {user.display_name}: {e}"
                )
                await interaction.followup.send(
                    "❌ Ошибка при выдаче роли Новичок.", ephemeral=True
                )
                return

            # Создаем embed с результатом
            success_embed = discord.Embed(
                title="✅ Заявка принята!",
                description=f"Заявка игрока {user.mention} успешно принята модератором {interaction.user.mention}",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            success_embed.add_field(
                name="👤 Новый участник",
                value=f"{user.display_name} ({user.mention})",
                inline=True,
            )

            success_embed.add_field(
                name="👮 Модератор",
                value=f"{interaction.user.display_name}",
                inline=True,
            )

            # Информация о ролях после изменений
            role_info = []
            current_roles = [
                role.name for role in user.roles if role.name != "@everyone"
            ]

            if guest_role and guest_role.name not in current_roles:
                role_info.append(f"❌ Удалена: {guest_role.mention}")
            if newbie_role and newbie_role.name in current_roles:
                role_info.append(f"✅ Выдана: {newbie_role.mention}")

            success_embed.add_field(
                name="🎯 Изменения ролей",
                value=(
                    "\n".join(role_info)
                    if role_info
                    else f"✅ Выдана: {newbie_role.mention}"
                ),
                inline=True,
            )

            success_embed.add_field(
                name="👥 Текущие роли",
                value=(
                    ", ".join([f"`{role}`" for role in current_roles])
                    if current_roles
                    else "Только базовые роли"
                ),
                inline=False,
            )

            success_embed.set_footer(
                text="Заявка обработана"
            )

            # Обновляем сообщение
            await interaction.edit_original_response(embed=success_embed, view=None)

            # Фиксируем никнейм после выдачи роли Новичок (как в команде /role)
            try:
                current_nick = user.display_name
                await user.edit(
                    nick=current_nick,
                    reason=f"Фиксация никнейма после принятия заявки модератором {interaction.user.display_name}",
                )
                logger.info(
                    f"✅ Никнейм '{current_nick}' зафиксирован для {user.display_name} при принятии заявки через кнопку"
                )
            except discord.Forbidden:
                logger.warning(
                    f"⚠️ Нет прав для фиксации никнейма у {user.display_name}"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка фиксации никнейма у {user.display_name}: {e}")

            # Отправляем приветственное сообщение новичку
            welcome_message = f"""🎉 {user.mention} **Добро пожаловать в Деревню VLG!**

✅ Ваша заявка **принята**! Теперь вы официально житель нашей Деревни.

📋 **Что дальше:**
🔸 Изучите https://discord.com/channels/472365787445985280/1179490341980741763
🔸 Википедия по Деревне: https://discord.com/channels/472365787445985280/1322342577239756881/1322344519454294046
🔸 Когда вы на вайпе Деревни и сидите в Дискорде (в войсах), бот ведёт учёт и активным игрокам выдаёт роли: ⚫🔴🟡🟢
🔸 Как получите роль 🟢 - сможете повыситься до статуса Гость и выше."""

            # Создаем кнопки для пост-одобрения действий
            post_approval_view = PostApprovalView(self.user_id, interaction.channel.id)
            await safe_send_message(
                interaction.channel, welcome_message, view=post_approval_view
            )

            # Сохраняем Steam-ссылку в базу данных
            try:
                from handlers.tickets import save_steam_url_to_db

                await save_steam_url_to_db(self.user_id, self.steam_url)
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения Steam-ссылки: {e}")

            # Отправляем уведомление в мод-канал
            mod_channel = guild.get_channel(config.MOD_CHANNEL_ID)
            if mod_channel:
                mod_embed = discord.Embed(
                    title="✅ Заявка принята",
                    description=f"**Игрок:** {user.mention}\n**Модератор:** {interaction.user.mention}\n**Тикет:** {interaction.channel.mention}",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )
                await mod_channel.send(embed=mod_embed)

            # Отправляем отчет в канал "Личные дела"
            personal_files_channel = guild.get_channel(
                1226224193603895386
            )  # ID канала "Личные дела"
            logger.info(
                f"🔍 Канал личных дел найден: {personal_files_channel.name if personal_files_channel else 'НЕ НАЙДЕН'}"
            )

            if personal_files_channel:
                try:
                    await self.send_personal_file_report(
                        personal_files_channel, user, interaction.user, "Кнопка \"Одобрить\"", interaction.channel
                    )
                except Exception as e:
                    logger.error(f"❌ Критическая ошибка отправки в Личные дела: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    await log_error(
                        e,
                        f"❌ Критическая ошибка отправки в Личные дела для {user.display_name}",
                    )
            else:
                logger.error(
                    f"❌ Канал Личные дела не найден (ID: 1226224193603895386)"
                )

            # Планируем автоматическое удаление канала через 1 час после одобрения
            asyncio.create_task(
                self._schedule_channel_deletion(
                    interaction.channel, user, interaction.user
                )
            )

            logger.info(
                f"✅ Заявка принята: {user.display_name} модератором {interaction.user.display_name}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка принятия заявки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при принятии заявки.", ephemeral=True
            )

    async def _schedule_channel_deletion(self, channel, user, moderator):
        """Планирует удаление канала заявки через 1 час после принятия"""
        try:
            # Ждем 1 час (3600 секунд)
            await asyncio.sleep(3600)

            # Проверяем, что канал все еще существует
            if channel and hasattr(channel, "guild") and channel.guild:
                try:
                    # Проверяем что канал действительно существует на сервере
                    test_channel = channel.guild.get_channel(channel.id)
                    if test_channel:
                        # Удаляем канал втихую без предупреждения
                        await channel.delete(
                            reason=f"Автоматическое удаление через 6 часов после принятия заявки {user.display_name} модератором {moderator.display_name}"
                        )

                        # Удаляем из кэша владельцев тикетов
                        del_ticket_owner(channel.id)

                        logger.info(
                            f"🗑️ Автоматически удален канал заявки {channel.name} пользователя {user.display_name} через 1 час после принятия"
                        )

                        # Отправляем уведомление в мод-канал ПЕРЕД удалением канала
                        mod_channel = channel.guild.get_channel(config.MOD_CHANNEL_ID)
                        if mod_channel:
                            auto_delete_embed = discord.Embed(
                                title="🗑️ Автоматическое удаление заявки",
                                description=f"**Игрок:** {user.display_name}\n**Модератор:** {moderator.display_name}\n**Канал:** {channel.name}",
                                color=0x808080,
                                timestamp=datetime.now(timezone.utc),
                            )
                            auto_delete_embed.add_field(
                                name="⏰ Время",
                                value="Удален через 1 час после принятия",
                                inline=False,
                            )
                            await mod_channel.send(embed=auto_delete_embed)
                    else:
                        logger.info(f"ℹ️ Канал {channel.name} уже был удален вручную")
                except discord.NotFound:
                    logger.info(f"ℹ️ Канал {channel.name} уже был удален")
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления канала {channel.name}: {e}")
            else:
                logger.info(f"ℹ️ Канал заявки уже недоступен для удаления")

        except asyncio.CancelledError:
            logger.info(
                f"⚠️ Автоматическое удаление канала {channel.name if channel else 'Unknown'} отменено"
            )
        except Exception as e:
            logger.error(f"❌ Критическая ошибка планирования удаления канала: {e}")

    @discord.ui.button(
        label="❌ Отклонить",
        style=discord.ButtonStyle.danger,
        custom_id="reject_application",
    )
    async def reject_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отклонение заявки"""
        await interaction.response.send_modal(
            RejectReasonModal(self.user_id, self.steam_url)
        )

    async def get_user_steam_url(self, user_id: int) -> str:
        """Получает сохраненный Steam URL пользователя"""
        try:
            # Пытаемся получить из локального кэша
            if hasattr(self, "user_steam_urls") and user_id in self.user_steam_urls:
                return self.user_steam_urls[user_id]

            # Пытаемся получить из глобального кэша тикетов
            from handlers.tickets import steam_cache

            return steam_cache.get(f"{user_id}_steam_url", None)
        except Exception as e:
            logger.error(f"❌ Ошибка получения Steam URL для {user_id}: {e}")
            await log_error(e, f"❌ Ошибка получения Steam URL для {user_id}")
            return None

    async def send_personal_file_report(self, channel, user, moderator, method, ticket_channel):
        """Отправляет детальный отчёт в канал личных дел"""
        try:
            # Получаем Steam URL из различных источников
            saved_steam_url = await self.get_user_steam_url(user.id)
            if not saved_steam_url:
                application_data = await self.find_user_application_data(user.guild, user)
                saved_steam_url = application_data.get("steam_url", "Не указано")

            # Получаем SteamID64 и часы в Rust
            steamid64 = "Не указано"
            rust_hours = "Не указано"
            final_nickname = user.display_name

            if saved_steam_url and saved_steam_url != "Не указано" and "steamcommunity.com" in saved_steam_url:
                try:
                    from handlers.steam_api import get_steamid64_from_url, steam_client

                    # Конвертируем Steam URL в SteamID64
                    steamid64 = await get_steamid64_from_url(saved_steam_url)
                    
                    if not steamid64:
                        from handlers.novichok import extract_steam_id_from_url
                        steamid64 = extract_steam_id_from_url(saved_steam_url)
                    if not steamid64:
                        steamid64 = "Ошибка конвертации"

                    logger.info(f"🔗 Конвертация Steam URL → SteamID64: {saved_steam_url} → {steamid64}")

                    # Получаем часы в Rust из контекста тикета
                    if ticket_channel:
                        try:
                            ctx = get_ctx(ticket_channel.id)
                            if ctx and ctx.rust_hours is not None:
                                rust_hours = str(ctx.rust_hours)
                                logger.info(f"🎮 Получены часы Rust из контекста: {rust_hours}")
                            else:
                                # Ищем часы в истории канала
                                rust_hours = await self.extract_rust_hours_from_channel(ticket_channel)
                        except Exception:
                            rust_hours = await self.extract_rust_hours_from_channel(ticket_channel)

                except Exception as e:
                    logger.error(f"❌ Ошибка обработки Steam данных: {e}")
                    steamid64 = "Ошибка обработки"

            # Создаем детальный embed отчёт
            current_time = datetime.now()
            report_embed = discord.Embed(
                title="📝 Личное дело игрока",
                description="Участник принят в Деревню VLG",
                color=0x00FF00,
                timestamp=current_time
            )

            # Основная информация об игроке  
            player_info = (
                f"👤 Игрок: {user.mention}\n"
                f"👮 Модератор: {moderator.mention}\n"
                f"📋 Метод принятия: {method}\n"
                f"Discord: **{user.display_name}**\n"
                f"Discord ID: `{user.id}`\n"
                f"Аккаунт создан: {user.created_at.strftime('%d.%m.%Y %H:%M')}"
            )
            report_embed.add_field(
                name="📋 Информация об участнике",
                value=player_info,
                inline=False
            )

            report_embed.add_field(
                name="👮 Модератор",
                value=f"{moderator.mention}",
                inline=True
            )

            report_embed.add_field(
                name="📋 Метод принятия",
                value=method,
                inline=True
            )

            # Steam данные с правильным форматированием
            steam_info_parts = []
            if saved_steam_url and saved_steam_url != "Не указано":
                steam_info_parts.append(f"Steam URL: {saved_steam_url}")
            else:
                steam_info_parts.append("Steam URL: Не указано")
            
            steam_info_parts.append(f"SteamID64: `{steamid64}`")
            
            # Получаем Steam никнейм из профиля
            steam_nickname = "Не указано"
            if steamid64 and steamid64 != "Не указано":
                try:
                    from handlers.steam_api import steam_client
                    steam_profile = await steam_client.get_player_summary(steamid64)
                    if steam_profile and steam_profile.get("success"):
                        steam_nickname = steam_profile.get("personaname", "Не указано")
                except Exception:
                    pass
            
            steam_info_parts.append(f"SteamNick: **{steam_nickname}**")
            steam_info_parts.append(f"Часы в Rust: {rust_hours}")
            
            report_embed.add_field(
                name="🔗 Steam данные",
                value="\n".join(steam_info_parts),
                inline=False
            )

            # Детали принятия
            acceptance_details = (
                f"Дата: {current_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"Роль выдана: <@&{config.NEWBIE_ROLE_ID}>\n"
                f"Никнейм зафиксирован: `{final_nickname}`"
            )
            report_embed.add_field(
                name="📋 Детали принятия",
                value=acceptance_details,
                inline=False
            )

            report_embed.set_footer(
                text=f"Принят через {method} модератором {moderator.display_name} • {current_time.strftime('%d.%m.%Y %H:%M')}"
            )

            report_embed.set_thumbnail(url=user.display_avatar.url)

            # Отправляем embed
            message_sent = await safe_send_message(channel, embed=report_embed)
            if message_sent:
                logger.info(f"✅ Успешно отправлен embed отчёт в Личные дела: {user.display_name}")
            else:
                logger.error(f"❌ Не удалось отправить embed отчёт в Личные дела: {user.display_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка создания отчёта в личные дела: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def extract_rust_hours_from_channel(self, channel):
        """Извлекает часы в Rust из истории канала"""
        try:
            async for message in channel.history(limit=30):
                if message.embeds:
                    for embed in message.embeds:
                        if embed.fields:
                            for field in embed.fields:
                                if field.name and ("час" in field.name.lower() or "rust" in field.name.lower()):
                                    if field.value and field.value.strip() not in ["Не указано", "0", ""]:
                                        hours_text = field.value.strip()
                                        # Извлекаем только числа
                                        import re
                                        numbers = re.findall(r'\d+', hours_text)
                                        if numbers:
                                            return numbers[0] + " часов"
                                        return hours_text
            return "Не указано в заявке"
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения часов Rust: {e}")
            return "Ошибка получения"

    async def get_steam_data_for_report(self, user_id: int, steam_url: str) -> dict:
        """Получает Steam данные для отчета в личные дела"""
        try:
            if not steam_url or steam_url == "Не указано":
                return {}

            from handlers.steam_api import steam_client
            from handlers.novichok import extract_steam_id_from_url

            # Извлекаем Steam ID из URL
            steam_id = extract_steam_id_from_url(steam_url)
            if not steam_id:
                return {}

            # Получаем данные из Steam API
            steam_data = await steam_client.get_player_summary(steam_id)
            if steam_data and steam_data.get('success'):
                return {
                    'steamid': steam_data.get('steamid', ''),
                    'personaname': steam_data.get('personaname', ''),
                }
            return {}

        except Exception as e:
            logger.error(f"❌ Ошибка получения Steam данных для отчета: {e}")
            return {}


class RejectReasonModal(discord.ui.Modal):
    def __init__(self, user_id: int, steam_url: str):
        super().__init__(title="Причина отклонения заявки")
        self.user_id = user_id
        self.steam_url = steam_url

        self.reason_input = discord.ui.TextInput(
            label="Причина отклонения",
            placeholder="Укажите причину отклонения заявки...",
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Обработка отклонения заявки"""
        await interaction.response.defer()

        try:
            guild = interaction.guild
            user = guild.get_member(self.user_id)
            reason = self.reason_input.value.strip()

            if not user:
                await interaction.followup.send(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            # Создаем embed с результатом
            reject_embed = discord.Embed(
                title="❌ Заявка отклонена",
                description=f"Заявка игрока {user.mention} отклонена модератором {interaction.user.mention}",
                color=0xFF0000,
                timestamp=datetime.now(timezone.utc),
            )

            reject_embed.add_field(
                name="👤 Заявитель",
                value=f"{user.display_name} ({user.mention})",
                inline=True,
            )

            reject_embed.add_field(
                name="👮 Модератор",
                value=f"{interaction.user.display_name}",
                inline=True,
            )

            reject_embed.add_field(name="📝 Причина", value=reason, inline=False)

            reject_embed.set_footer(text="Заявка отклонена")

            # Обновляем сообщение
            await interaction.edit_original_response(embed=reject_embed, view=None)

            # Отправляем сообщение заявителю
            rejection_message = f"""❌ {user.mention} **Ваша заявка отклонена**

**Причина:** {reason}

📋 **Что делать дальше:**
🔸 Не надо создавать новую заявку, продолжим решить проблемы в данной заявке и получить роль Новичок.
🔸 Отмечайте бота Помощника тут в чате и пишите "готово или проверь"
🔸 При необходимости обратитесь к жителям за помощью в https://discord.com/channels/472365787445985280/1178436876244361388"""

            await safe_send_message(interaction.channel, rejection_message)

            # Отправляем уведомление в мод-канал(бот-лог)
            mod_channel = guild.get_channel(config.MOD_CHANNEL_ID)
            if mod_channel:
                mod_embed = discord.Embed(
                    title="❌ Заявка отклонена",
                    description=f"**Игрок:** {user.mention}\n**Модератор:** {interaction.user.mention}\n**Причина:** {reason}\n**Тикет:** {interaction.channel.mention}",
                    color=0xFF0000,
                    timestamp=datetime.now(timezone.utc),
                )
                await mod_channel.send(embed=mod_embed)

            logger.info(
                f"❌ Заявка отклонена: {user.display_name} модератором {interaction.user.display_name}, причина: {reason}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка отклонения заявки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при отклонении заявки.", ephemeral=True
            )

    @discord.ui.button(
        label="🗑️ Удалить", style=discord.ButtonStyle.red, custom_id="delete_ticket"
    )
    async def delete_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка удаления тикета с подтверждением"""
        # Проверяем права: только автор заявки, Гражданин и Житель
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_ticket_owner = interaction.user.id == self.user_id
        has_permission = (
            any(role in user_roles for role in allowed_roles) or is_ticket_owner
        )

        if not has_permission:
            await interaction.response.send_message(
                "❌ Удалить этот тикет могут только автор заявки, а также любой Житель или Гражданин Деревни. У вас нет соответствующих прав.",
                ephemeral=True,
            )
            return

        # Первое подтверждение
        confirm_embed = discord.Embed(
            title="⚠️ Подтверждение удаления тикета",
            description="Вы уверены, что хотите удалить этот тикет?\n\n**Внимание:** Это действие нельзя отменить!",
            color=0xFF0000,
        )

        confirm_view = TicketDeleteConfirmView(self.user_id, interaction.user.id)
        await interaction.response.send_message(
            embed=confirm_embed, view=confirm_view, ephemeral=True
        )

    @discord.ui.button(
        label="🔄 Проверить заявку ещё раз",
        style=discord.ButtonStyle.gray,
        custom_id="recheck_application_1",
    )
    async def recheck_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка повторной проверки заявки"""
        # Проверяем права: ЛЮБОЙ пользователь может нажать (упрощаем для удобства)
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_ticket_owner = interaction.user.id == self.user_id
        has_permission = (
            any(role in user_roles for role in allowed_roles) or is_ticket_owner
        )

        if not has_permission:
            await interaction.response.send_message(
                "❌ Перепроверить этот тикет могут только автор заявки, а также любой Житель или Гражданин Деревни. У вас нет соответствующих прав.",
                ephemeral=True,
            )
            return

        try:
            # Отвечаем пользователю
            await interaction.response.send_message(
                "🔄 Начинаю повторную проверку заявки...", ephemeral=True
            )

            # Логируем действие
            logger.info(
                f"🔄 Повторная проверка заявки запрошена пользователем {interaction.user.display_name} в тикете {interaction.channel.name}"
            )

            # Получаем автора заявки
            ticket_owner = interaction.guild.get_member(self.user_id)
            if not ticket_owner:
                await interaction.edit_original_response(
                    content="❌ Не удалось найти автора заявки."
                )
                return

            # Очищаем кэш Steam для свежей проверки
            try:
                from handlers.steam_api import steam_client
                from handlers.novichok import extract_steam_id_from_url

                # Если есть сохраненная Steam-ссылка
                if hasattr(self, "steam_url") and self.steam_url:
                    steam_id = extract_steam_id_from_url(self.steam_url)
                    if steam_id:
                        steam_client.force_cache_clear_for_profile(steam_id)
                        logger.info(f"🗑️ Очищен кэш Steam для повторной проверки")
            except Exception as e:
                logger.error(f"Ошибка очистки кэша Steam: {e}")

            # Импортируем и запускаем анализ заявки
            from handlers.tickets import TicketHandler

            # Создаем временный экземпляр обработчика
            bot = interaction.client
            ticket_handler = bot.get_cog("TicketHandler")

            if ticket_handler:
                # Запускаем анализ заявки
                await ticket_handler.analyze_and_respond_to_application(
                    interaction.channel, ticket_owner
                )

                await interaction.edit_original_response(
                    content="✅ Повторная проверка заявки запущена!"
                )

        except Exception as e:
            logger.error(f"❌ Ошибка повторной проверки заявки: {e}")
            try:
                await interaction.edit_original_response(
                    content="❌ Произошла ошибка при повторной проверке заявки."
                )
            except:
                pass


class PostApprovalView(discord.ui.View):
    def __init__(self, user_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем права модератора"""
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id

        if not any(role in user_roles for role in admin_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для использования этих кнопок.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="🗑️ Удалить заявку",
        style=discord.ButtonStyle.danger,
        custom_id="delete_ticket_post",
    )
    async def delete_ticket_post(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Удаление заявки с подтверждением"""
        confirm_embed = discord.Embed(
            title="⚠️ Подтверждение удаления заявки",
            description="Вы уверены, что хотите удалить эту заявку? Канал будет удален через 15 секунд после подтверждения.",
            color=0xFF0000,
        )

        confirm_view = ConfirmTicketDeleteView(self.user_id, self.channel_id)
        await interaction.response.send_message(
            embed=confirm_embed, view=confirm_view, ephemeral=True
        )

    @discord.ui.button(
        label="📋 Напомнить правила",
        style=discord.ButtonStyle.secondary,
        custom_id="remind_rules_post",
    )
    async def remind_rules_post(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Напоминание правил новичку"""
        user = interaction.guild.get_member(self.user_id)
        if not user:
            await interaction.response.send_message(
                "❌ Пользователь не найден на сервере.", ephemeral=True
            )
            return

        await interaction.response.defer()

        rules_message = f"""📋 {user.mention} **Напоминаем важные правила Деревни:**

🎤 **В Деревне обязательно важно сидеть в войс каналах Деревни.**

🔧 Вы можете создать приватный голосовой канал себе https://discord.com/channels/472365787445985280/1264874500693037197 и через его настройки закрыть её для себя и пусть туда только своих друзей.

👑 Вы как владелец канала сможете кикнуть любого кто Вам помешает.

💡 **Советуем попробовать.** Все настройки войс канала сохраняются."""

        await safe_send_message(interaction.channel, rules_message)

        await interaction.followup.send(
            f"✅ Правила напомнены пользователю {user.mention}", ephemeral=True
        )

        logger.info(
            f"📋 Правила напомнены пользователю {user.display_name} модератором {interaction.user.display_name}"
        )

    @discord.ui.button(
        label="❌ Отменить одобрение",
        style=discord.ButtonStyle.primary,
        custom_id="cancel_approval_post",
    )
    async def cancel_approval_post(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отмена одобрения с подтверждением"""
        user = interaction.guild.get_member(self.user_id)
        if not user:
            await interaction.response.send_message(
                "❌ Пользователь не найден на сервере.", ephemeral=True
            )
            return

        confirm_embed = discord.Embed(
            title="⚠️ Подтверждение отмены одобрения",
            description=f"Вы уверены, что хотите отменить одобрение пользователя {user.mention}?\n\n**Что произойдет:**\n🔹 Роль **Новичок** будет снята\n🔹 Роль **Прохожий** будет возвращена",
            color=0xFF9900,
        )

        confirm_view = ConfirmCancelApprovalView(self.user_id, self.channel_id)
        await interaction.response.send_message(
            embed=confirm_embed, view=confirm_view, ephemeral=True
        )


class ConfirmTicketDeleteView(discord.ui.View):
    def __init__(self, user_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.channel_id = channel_id

    @discord.ui.button(label="🗑️ Удалить", style=discord.ButtonStyle.danger)
    async def confirm_delete_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Подтверждение удаления тикета"""
        await interaction.response.send_message(
            "⏰ Заявка будет удалена через 15 секунд...", ephemeral=False
        )

        # Логируем действие
        logger.info(
            f"🗑️ Тикет {interaction.channel.name} будет удален через 15 секунд пользователем {interaction.user.display_name}"
        )

        # Ждем 15 секунд
        await asyncio.sleep(15)

        try:
            # Удаляем канал
            await interaction.channel.delete(
                reason=f"Заявка удалена пользователем {interaction.user.display_name} после таймера"
            )
            logger.info(f"🗑️ Тикет удален пользователем {interaction.user.display_name}")
        except Exception as e:
            logger.error(f"❌ Ошибка удаления тикета: {e}")


    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary)
    async def cancel_delete_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отмена удаления"""
        await interaction.response.edit_message(
            content="❌ Удаление отменено.", embed=None, view=None
        )


class RecheckApplicationView(discord.ui.View):
    def __init__(self, user_id: int = None, steam_url: str = None):
        super().__init__(timeout=None)  # Постоянная кнопка
        self.user_id = user_id or 0
        self.steam_url = steam_url or ""

    @discord.ui.button(
        label="🔄 Проверить заявку ещё раз",
        style=discord.ButtonStyle.gray,
        custom_id="recheck_application_0",
    )
    async def recheck_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка повторной проверки заявки"""
        try:
            # Отвечаем пользователю
            await interaction.response.send_message(
                "🔄 Начинаю повторную проверку заявки...", ephemeral=True
            )

            # Логируем действие
            logger.info(
                f"🔄 Повторная проверка заявки запрошена пользователем {interaction.user.display_name} в тикете {interaction.channel.name}"
            )

            # Получаем автора заявки
            ticket_owner = interaction.guild.get_member(self.user_id)
            if not ticket_owner:
                await interaction.edit_original_response(
                    content="❌ Не удалось найти автора заявки."
                )
                return

            # Очищаем кэш Steam для свежей проверки
            try:
                from handlers.steam_api import steam_client
                from handlers.novichok import extract_steam_id_from_url

                # Если есть сохраненная Steam-ссылка
                if self.steam_url:
                    steam_id = extract_steam_id_from_url(self.steam_url)
                    if steam_id:
                        steam_client.force_cache_clear_for_profile(steam_id)
                        logger.info(f"🗑️ Очищен кэш Steam для повторной проверки")
            except Exception as e:
                logger.error(f"Ошибка очистки кэша Steam: {e}")

            # Импортируем и запускаем анализ заявки
            from handlers.tickets import TicketHandler

            # Создаем временный экземпляр обработчика
            bot = interaction.client
            handler = TicketHandler(bot)

            # Запускаем анализ заявки
            await handler.analyze_and_respond_to_application(
                interaction.channel, ticket_owner
            )

            await interaction.edit_original_response(
                content="✅ Повторная проверка заявки запущена!"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка повторной проверки заявки: {e}")
            try:
                await interaction.edit_original_response(
                    content="❌ Произошла ошибка при повторной проверке заявки."
                )
            except:
                pass


class ConfirmCancelApprovalView(discord.ui.View):
    def __init__(self, user_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.channel_id = channel_id

    @discord.ui.button(label="✅ Отменить одобрение", style=discord.ButtonStyle.primary)
    async def confirm_cancel_approval(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Подтверждение отмены одобрения"""
        user = interaction.guild.get_member(self.user_id)
        if not user:
            await interaction.response.send_message(
                "❌ Пользователь не найден на сервере.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            guild = interaction.guild
            newbie_role = guild.get_role(NEWBIE_ROLE_ID)
            guest_role = guild.get_role(GUEST_ROLE_ID)

            # Снимаем роль Новичок
            if newbie_role and newbie_role in user.roles:
                await user.remove_roles(
                    newbie_role,
                    reason=f"Отмена одобрения заявки модератором {interaction.user.display_name}",
                )
                logger.info(f"🔄 Снята роль Новичок у {user.display_name}")

            # Выдаем роль Прохожий
            if guest_role:
                await user.add_roles(
                    guest_role,
                    reason=f"Возврат роли Прохожий после отмены одобрения модератором {interaction.user.display_name}",
                )
                logger.info(f"🔄 Выдана роль Прохожий пользователю {user.display_name}")

                # Отправляем уведомление в канал
                channel = guild.get_channel(self.channel_id)
                if channel:
                    cancel_message = f"""⚠️ {user.mention} **Ваше одобрение отменено модератором {interaction.user.mention}**

🔄 Вам возвращена роль **Прохожий**.

📋 **Что делать дальше:**
🔸 Прочитайте тут в чате возможную причину отказа от одобрения Вашей заявки
🔸 Исправьте все недочёты, а после нажмите кнопку "Проверить заявку ещё раз" в самом начале данного тикета
🔸 Если будут вопросы, можете задать их жителям в https://discord.com/channels/472365787445985280/1178436876244361388"""

                    await safe_send_message(channel, cancel_message)

                await interaction.followup.send(
                    f"✅ Одобрение отменено: {user.mention} получил роль Прохожий",
                    ephemeral=True,
                )

                # Отправляем уведомление в мод-канал
                mod_channel = guild.get_channel(config.MOD_CHANNEL_ID)
                if mod_channel:
                    mod_embed = discord.Embed(
                        title="⚠️Одобрение отменено",
                        description=f"**Игрок:** {user.mention}\n**Модератор:** {interaction.user.mention}\n**Тикет:** <#{self.channel_id}>",
                        color=0xFF9900,
                        timestamp=datetime.now(timezone.utc),
                    )
                    await mod_channel.send(embed=mod_embed)

                logger.info(
                    f"⚠️ Одобрение отменено: {user.display_name} модератором {interaction.user.display_name}"
                )
            else:
                await interaction.followup.send(
                    "❌ Роль 'Прохожий' не найдена.", ephemeral=True
                )

        except Exception as e:
            logger.error(f"❌ Ошибка отмены одобрения: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при отмене одобрения.", ephemeral=True
            )

    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary, custom_id="cancel_cancel_approval_v2")
    async def cancel_cancel_approval(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отмена отмены одобрения"""
        await interaction.response.edit_message(
            content="❌ Отмена одобрения отменена.", embed=None, view=None
        )


# Глобальный словарь для хранения активных задач удаления
active_deletion_tasks = {}


class TicketDeleteConfirmView(discord.ui.View):
    def __init__(self, ticket_owner_id: int, deleter_id: int):
        super().__init__(timeout=None)
        self.ticket_owner_id = ticket_owner_id
        self.deleter_id = deleter_id

    @discord.ui.button(label="✅ Да, удалить", style=discord.ButtonStyle.danger)
    async def confirm_delete_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Подтверждение удаления - запускаем таймер"""
        await interaction.response.defer()

        try:
            # Создаем embed с таймером
            timer_embed = discord.Embed(
                title="⏰ Заявка будет удалена через 30 секунд...",
                description="Нажмите кнопку ниже чтобы отменить удаление",
                color=0xFF9900,
                timestamp=datetime.now(timezone.utc),
            )

            # Создаем view с кнопкой отмены
            cancel_view = TicketDeleteCancelView(
                self.ticket_owner_id, self.deleter_id, interaction.channel.id
            )

            # Отправляем сообщение с таймером в канал тикета
            timer_message = await safe_send_message(
                interaction.channel, embed=timer_embed, view=cancel_view
            )

            # Создаем задачу удаления
            deletion_task = asyncio.create_task(
                self._delete_after_delay(
                    interaction.channel, interaction.user, timer_message, cancel_view
                )
            )

            # Сохраняем задачу в глобальном словаре
            active_deletion_tasks[interaction.channel.id] = deletion_task

            # Отвечаем пользователю
            await interaction.edit_original_response(
                content="⏰ Удаление запланировано. Таймер запущен в канале тикета.",
                embed=None,
                view=None,
            )

            logger.info(
                f"⏰ Запущен таймер удаления для {interaction.channel.name} пользователем {interaction.user.display_name}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка запуска таймера удаления: {e}")
            await interaction.edit_original_response(
                content="❌ Произошла ошибка при запуске таймера удаления.",
                embed=None,
                view=None,
            )

    async def _delete_after_delay(self, channel, deleter, timer_message, cancel_view):
        """Удаляет канал через 30 секунд"""
        try:
            await asyncio.sleep(30)

            # Проверяем, что задача не была отменена
            if channel.id in active_deletion_tasks:
                # Отключаем кнопку отмены
                for item in cancel_view.children:
                    item.disabled = True

                # Обновляем сообщение
                final_embed = discord.Embed(
                    title="🗑️ Удаляем заявку...",
                    description="Время истекло. Канал будет удален через несколько секунд.",
                    color=0xFF0000,
                )

                try:
                    await timer_message.edit(embed=final_embed, view=cancel_view)
                except:
                    pass

                # Удаляем канал
                await asyncio.sleep(3)
                await channel.delete(
                    reason=f"Удален пользователем {deleter.display_name} после таймера"
                )

                # Удаляем из активных задач
                if channel.id in active_deletion_tasks:
                    del active_deletion_tasks[channel.id]

                logger.info(
                    f"🗑️ Канал {channel.name} удален пользователем {deleter.display_name} после истечения таймера"
                )

        except asyncio.CancelledError:
            logger.info(
                f"⚠️ Удаление канала {channel.name if channel else 'Unknown'} отменено"
            )
            # Удаляем из активных задач при отмене
            if hasattr(channel, "id") and channel.id in active_deletion_tasks:
                del active_deletion_tasks[channel.id]
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении канала: {e}")


class TicketDeleteCancelView(discord.ui.View):
    def __init__(self, ticket_owner_id: int, deleter_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.ticket_owner_id = ticket_owner_id
        self.deleter_id = deleter_id
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем права на отмену удаления"""
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_ticket_owner = interaction.user.id == self.ticket_owner_id
        is_deleter = interaction.user.id == self.deleter_id
        has_permission = any(role in user_roles for role in allowed_roles)

        # Автор заявки, инициатор удаления или модератор могут отменить
        if not (is_ticket_owner or is_deleter or has_permission):
            await interaction.response.send_message(
                "❌ Только автор заявки, инициатор удаления или модераторы могут отменить удаление.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="❌ Отменить удаление", style=discord.ButtonStyle.primary)
    async def cancel_deletion(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отмена удаления канала"""
        try:
            # Отменяем задачу удаления
            if self.channel_id in active_deletion_tasks:
                task = active_deletion_tasks[self.channel_id]
                task.cancel()
                del active_deletion_tasks[self.channel_id]

            # Отключаем кнопку
            button.disabled = True

            # Создаем embed об отмене
            cancel_embed = discord.Embed(
                title="✅ Удаление отменено",
                description=f"Удаление заявки отменено пользователем {interaction.user.display_name}",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            await interaction.response.edit_message(embed=cancel_embed, view=self)

            logger.info(
                f"✅ Удаление канала {interaction.channel.name} отменено пользователем {interaction.user.display_name}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка отмены удаления: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при отмене удаления.", ephemeral=True
            )


async def setup(bot):
    """Настройка постоянных view для кнопок и добавление Cog"""
    bot.add_view(TicketActionView(0, ""))  # Dummy view для загрузки
    bot.add_view(AutoFixConfirmationView(0, "", "", []))  # Dummy view для загрузки
    bot.add_view(PostApprovalView(0, 0))  # Dummy view для загрузки
    bot.add_view(ConfirmCancelApprovalView(0, 0))  # Dummy view для загрузки
    bot.add_view(TicketDeleteConfirmView(0, 0))  # Dummy view для загрузки
    bot.add_view(TicketDeleteCancelView(0, 0, 0))  # Dummy view для загрузки
    bot.add_view(RecheckApplicationView(0, ""))  # Dummy view для загрузки
    logger.info(
        "✅ Все постоянные views добавлены: TicketActionView, AutoFixConfirmationView, PostApprovalView, ConfirmCancelApprovalView, TicketDeleteConfirmView, TicketDeleteCancelView, RecheckApplicationView"
    )

    # Добавляем Cog с командами
    await bot.add_cog(Novichok(bot))
    logger.info("✅ Novichok Cog добавлен с командами")


from discord.ext import commands


class Novichok(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.user_steam_urls = {}  # Словарь для хранения Steam URL пользователей

    async def cog_load(self):
        self.logger.info(f"Загружен модуль {self.__class__.__name__}")

    async def cog_unload(self):
        self.logger.info(f"Выгружен модуль {self.__class__.__name__}")

    async def save_user_steam_url(self, user_id: int, steam_url: str):
        """Сохраняет Steam URL пользователя"""
        try:
            self.user_steam_urls[user_id] = steam_url
            logger.info(
                f"💾 Сохранена Steam-ссылка для пользователя {user_id}: {steam_url}"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения Steam URL для {user_id}: {e}")
            await log_error(e, f"❌ Ошибка сохранения Steam URL для {user_id}")

    async def get_user_steam_url(self, user_id: int) -> str:
        """Получает сохраненный Steam URL пользователя"""
        try:
            return self.user_steam_urls.get(user_id, None)
        except Exception as e:
            logger.error(f"❌ Ошибка получения Steam URL для {user_id}: {e}")
            await log_error(e, f"❌ Ошибка получения Steam URL для {user_id}")
            return None

    @commands.command(name="готов", aliases=["проверь", "check", "ready"])
    async def check_application_command(self, ctx):
        """Команда для проверки заявки"""
        try:
            # Проверяем, что команда вызвана в канале тикета
            if not ctx.channel.name.startswith("new_"):
                await ctx.send(
                    "❌ Эта команда работает только в каналах заявок.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            # Запускаем анализ и обработку заявки
            applicant = ctx.author
            await self.analyze_and_respond_to_application(ctx.channel, applicant)

            # Удаляем сообщение пользователя с командой
            await ctx.message.delete(delay=2)

            self.logger.info(
                f"🔄 Заявка {applicant.display_name} запрошена на перепроверку командой /готов"
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при обработке команды /готов: {e}")
            await ctx.send(
                "❌ Произошла ошибка при обработке команды. Попробуйте позже.",
                ephemeral=True,
                delete_after=5,
            )

    @app_commands.command(name="role", description="Выдать роль Новичок участнику")
    @app_commands.describe(member="Участник, которому нужно выдать роль Новичок")
    async def issue_role_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Выдача роли Новичок участнику"""
        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id
        if not any(role in user_roles for role in allowed_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для выдачи ролей.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            # Логируем действие
            self.logger.info(
                f"Выдача роли запрошена: {interaction.user.display_name} → {member.display_name}"
            )

            # Получаем роли
            novichok_role = discord.utils.get(
                interaction.guild.roles, id=config.NEWBIE_ROLE_ID
            )
            prokhozhy_role = discord.utils.get(
                interaction.guild.roles, id=config.GUEST_ROLE_ID
            )

            if not novichok_role:
                await interaction.followup.send(
                    "❌ Роль 'Новичок' не найдена на сервере.", ephemeral=True
                )
                return

            if not prokhozhy_role:
                await interaction.followup.send(
                    "❌ Роль 'Прохожий' не найдена на сервере.", ephemeral=True
                )
                return

            # Проверяем, есть ли у участника роль "Прохожий"
            if prokhozhy_role not in member.roles:
                await interaction.followup.send(
                    f"❌ У участника {member.mention} нет роли 'Прохожий'.",
                    ephemeral=True,
                )
                return

            # Убираем роль "Прохожий" и выдаем роль "Новичок"
            try:
                await member.remove_roles(
                    prokhozhy_role, reason="Замена роли Прохожий на Новичок"
                )
                await member.add_roles(
                    novichok_role,
                    reason=f"Роль выдана модератором {interaction.user.display_name}",
                )
                self.logger.info(f"✅ Роли успешно обновлены для {member.display_name}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка при выдаче/удалении ролей: {e}")
                await interaction.followup.send(
                    f"❌ Произошла ошибка при выдаче роли. Обратитесь к администратору.",
                    ephemeral=True,
                )
                return

            # Фиксируем никнейм
            try:
                current_nick = member.display_name
                await member.edit(
                    nick=current_nick,
                    reason=f"Фиксация никнейма после выдачи роли Новичок",
                )
                self.logger.info(
                    f"✅ Никнейм '{current_nick}' зафиксирован для {member.display_name}"
                )
            except discord.Forbidden:
                self.logger.warning(
                    f"⚠️ Нет прав для фиксации никнейма у {member.display_name}"
                )
            except Exception as e:
                self.logger.error(f"❌ Ошибка фиксации никнейма: {e}")

            # Сообщение об успехе
            success_embed = discord.Embed(
                title="✅ Роль выдана",
                description=f"Участнику {member.mention} выдана роль <@&{novichok_role.id}>",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )
            success_embed.add_field(
                name="👮 Модератор", value=interaction.user.mention, inline=True
            )
            await interaction.followup.send(embed=success_embed)

            # Уведомление в мод-канал
            mod_channel = self.bot.get_channel(config.MOD_CHANNEL_ID)
            if mod_channel:
                mod_embed = discord.Embed(
                    title="✅ Роль выдана",
                    description=f"**Игрок:** {member.mention}\n**Модератор:** {interaction.user.mention}",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )
                await mod_channel.send(embed=mod_embed)

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /role: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )

    @app_commands.command(name="check_nick", description="Проверить никнейм участника")
    @app_commands.describe(member="Участник для проверки никнейма")
    async def check_nickname_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Проверка никнейма участника"""
        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id
        if not any(role in user_roles for role in allowed_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для проверки никнеймов.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            # Извлекаем информацию о пользователе
            current_nick = member.display_name
            self.logger.info(
                f"Проверка никнейма запрошена: {interaction.user.display_name} → {member.display_name}"
            )

            # Оцениваем никнейм на соответствие требованиям
            nickname_valid, nickname_errors = self.validate_nickname(current_nick)
            self.logger.info(
                f"Результат проверки никнейма: valid={nickname_valid}, errors={nickname_errors}"
            )

            # Формируем ответ в зависимости от результатов
            if nickname_valid:
                # Никнейм соответствует требованиям
                success_embed = discord.Embed(
                    title="✅ Никнейм соответствует требованиям",
                    description=f"Никнейм участника {member.mention} оформлен корректно.",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )
                await interaction.followup.send(embed=success_embed, ephemeral=True)

            else:
                # Никнейм не соответствует требованиям
                error_embed = discord.Embed(
                    title="❌ Никнейм не соответствует требованиям",
                    description=f"К сожалению, никнейм участника {member.mention} не может быть одобрен.",
                    color=0xFF0000,
                    timestamp=datetime.now(timezone.utc),
                )

                # Добавляем информацию об ошибках
                error_message = "\n".join([f"• {error}" for error in nickname_errors])
                error_embed.add_field(
                    name="📝 Найденные ошибки", value=error_message, inline=False
                )

                await interaction.followup.send(embed=error_embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /check_nick: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )

    def validate_nickname(self, nickname):
        """Проверка никнейма через новую строгую систему валидации"""
        from utils.validators import is_nickname_format_valid

        try:
            is_valid, error_message, _ = is_nickname_format_valid(nickname)

            if is_valid:
                return True, []
            else:
                # Возвращаем список с одной ошибкой для совместимости
                return False, [error_message]

        except Exception as e:
            logger.error(f"❌ Ошибка валидации никнейма '{nickname}': {e}")
            return False, ["Произошла ошибка при проверке никнейма"]

    def validate_rust_hours(self, rust_hours):
        """Проверка часов в Rust"""
        is_valid = True
        errors = []

        # Проверка формата: число или "не указано"
        if rust_hours.lower() != "не указано":
            try:
                hours = int(rust_hours)
                if hours < 0:
                    is_valid = False
                    errors.append("Количество часов не может быть отрицательным.")
            except ValueError:
                is_valid = False
                errors.append("Неверный формат часов. Укажите число или 'не указано'.")

        return is_valid, errors

    async def get_application_info(
        self, channel: discord.TextChannel, applicant: discord.Member
    ):
        """Получение информации о заявке участника"""
        steam_url = "Не указано"
        rust_hours = "Не указано"
        how_found = "Не указано"

        # --- Новый блок: проверка description у заявки Новичка ---
        for message in await channel.history(limit=50).flatten():
            for embed in message.embeds:
                if embed.description:
                    # Ищем Steam ссылку в описании
                    matches = re.findall(
                        r'https?://steamcommunity\.com/(?:profiles|id)/[^\s\)\]\>"<]+',
                        embed.description,
                    )
                    if matches and steam_url == "Не указано":
                        steam_url = matches[0]

                    # Ищем часы Rust (например "223 ч", "222 часов", "300 hours")
                    hours_match = re.search(
                        r'(\d+)\s*(?:ч|час|часов|hours)',
                        embed.description.lower(),
                    )
                    if hours_match and rust_hours == "Не указано":
                        rust_hours = hours_match.group(1)


        # Ищем сообщения с информацией в канале
        async for message in channel.history(limit=50):
            if message.embeds:
                for embed in message.embeds:
                    if embed.fields:
                        for field in embed.fields:
                            field_name = field.name.lower() if field.name else ""
                            field_value = field.value.strip() if field.value else ""

                            if not field_value:
                                continue

                            # Определяем тип поля по ключевым словам
                            if any(word in field_name for word in ["steam", "стим"]):
                                if "steamcommunity.com" in field_value:
                                    steam_url = field_value
                                # Также ищем в тексте поля
                                elif "steamcommunity.com" in field_value:
                                    # Извлекаем Steam URL из текста
                                    import re

                                    steam_pattern = r'https?://steamcommunity\.com/(?:profiles|id)/[^\s\)\]\>"<]+'
                                    matches = re.findall(steam_pattern, field_value)
                                    if matches:
                                        steam_url = matches[0]
                            elif any(
                                word in field_name
                                for word in [
                                    "часов",
                                    "rust",
                                    "раст",
                                    "игры",
                                    "время",
                                    "опыт",
                                ]
                            ):
                                rust_hours = field_value
                            elif any(
                                word in field_name
                                for word in ["узнали", "пригласил", "друг", "откуда"]
                            ):
                                how_found = field_value

        return steam_url, rust_hours, how_found

    @app_commands.command(
        name="clear_steam", description="Очистить кэш Steam для участника"
    )
    @app_commands.describe(member="Участник для очистки кэша Steam")
    async def clear_steam_cache_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Очистка кэша Steam для участника"""
        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id
        if not any(role in user_roles for role in allowed_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для очистки кэша.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            # Импортируем функции для работы со Steam API
            from handlers.steam_api import steam_client
            from handlers.novichok import extract_steam_id_from_url

            # Ищем Steam URL в канале
            steam_url = "Не указано"
            async for message in interaction.channel.history(limit=20):
                if message.embeds:
                    for embed in message.embeds:
                        if embed.fields:
                            for field in embed.fields:
                                if (
                                    field.name
                                    and "steam" in field.name.lower()
                                    and field.value
                                ):
                                    if "steamcommunity.com" in field.value:
                                        steam_url = field.value
                                        break

            # Если Steam URL найден, очищаем кэш
            if steam_url != "Не указано":
                steam_id = extract_steam_id_from_url(steam_url)
                if steam_id:
                    steam_client.force_cache_clear_for_profile(steam_id)
                    await interaction.followup.send(
                        f"✅ Кэш Steam для участника {member.mention} очищен.",
                        ephemeral=True,
                    )
                    self.logger.info(
                        f"✅ Кэш Steam для {member.display_name} очищен модератором {interaction.user.display_name}"
                    )
                else:
                    await interaction.followup.send(
                        "❌ Не удалось извлечь Steam ID из URL.", ephemeral=True
                    )
            else:
                await interaction.followup.send(
                    "❌ Steam URL не найден в канале.", ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при очистке кэша Steam: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при очистке кэша. Попробуйте позже.",
                ephemeral=True,
            )

    @app_commands.command(
        name="info", description="Показать информацию о заявке участника"
    )
    @app_commands.describe(member="Участник для показа информации о заявке")
    async def show_application_info_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Показать информацию о заявке участника"""
        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id
        if not any(role in user_roles for role in allowed_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для просмотра информации о заявках.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            # Получаем информацию о заявке
            steam_url, rust_hours, how_found = await self.get_application_info(
                interaction.channel, member
            )

            # Формируем embed с информацией
            info_embed = discord.Embed(
                title="ℹ️ Информация о заявке",
                description=f"Информация о заявке участника {member.mention}",
                color=0x00FFFF,
                timestamp=datetime.now(timezone.utc),
            )

            info_embed.add_field(name="🎮 Steam", value=steam_url, inline=False)
            info_embed.add_field(name="⏰ Rust (часов)", value=rust_hours, inline=True)
            info_embed.add_field(name="Откуда узнали", value=how_found, inline=True)

            # Отправляем embed
            await interaction.followup.send(embed=info_embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /info: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )

    @app_commands.command(
        name="apply_fixes",
        description="Применить автоматические исправления к никнейму",
    )
    @app_commands.describe(member="Участник для применения исправлений никнейма")
    async def apply_nickname_fixes_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Применение автоматических исправлений к никнейму участника"""
        await interaction.response.defer()

        try:
            # Извлекаем информацию о пользователе
            original_nickname = member.display_name
            fixed_nickname, fixes_applied = auto_fix_nickname(original_nickname)
            if fixed_nickname != original_nickname:
                # Применяем исправление автоматически
                try:
                    await member.edit(nick=fixed_nickname)
                    await interaction.followup.send(
                        f"✅ Никнейм участника {member.mention} автоматически исправлен: {original_nickname} → {fixed_nickname}",
                        ephemeral=True,
                    )
                    self.logger.info(
                        f"✅ Никнейм {member.display_name} автоматически исправлен: {original_nickname} → {fixed_nickname}"
                    )
                except discord.Forbidden:
                    await interaction.followup.send(
                        "❌ У меня нет прав для изменения никнейма этого участника.",
                        ephemeral=True,
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Ошибка при применении исправлений к никнейму: {e}"
                    )
                    await interaction.followup.send(
                        "❌ Произошла ошибка при применении исправлений.",
                        ephemeral=True,
                    )
            else:
                await interaction.followup.send(
                    "✅ Никнейм не требует исправлений.", ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /apply_fixes: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )

    @app_commands.command(
        name="recheck", description="Запустить повторную проверку заявки"
    )
    @app_commands.describe(member="Участник для повторной проверки заявки")
    async def recheck_application_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Запуск повторной проверки заявки"""
        logger.info(
            f"🔄 Начинаем перепроверку заявки в канале {interaction.channel.name} пользователем {interaction.user.display_name}"
        )
        await interaction.response.defer()

        try:
            # Запускаем анализ и обработку заявки
            await self.analyze_and_respond_to_application(interaction.channel, member)
            await interaction.followup.send(
                "🔄 Заявка отправлена на повторную проверку.", ephemeral=True
            )
            self.logger.info(
                f"🔄 Заявка {member.display_name} отправлена на повторную проверку командой /recheck"
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /recheck: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )

    async def analyze_and_respond_to_application(
        self, channel: discord.TextChannel, applicant: discord.Member
    ):
        """Анализ заявки и отправка ответа"""
        try:
            # Извлекаем информацию о пользователе
            current_nick = applicant.display_name
            self.logger.info(
                f"Начинаем анализ заявки: {current_nick} (ID: {applicant.id})"
            )

            # Запрашиваем данные о пользователе из Steam API
            steam_url, rust_hours, how_found = await self.get_application_info(
                channel, applicant
            )

            # Автоматическое исправление никнейма
            original_nickname = applicant.display_name
            fixed_nickname, fixes_applied = auto_fix_nickname(original_nickname)
            if fixed_nickname != original_nickname:
                # Применяем исправление автоматически
                try:
                    await applicant.edit(nick=fixed_nickname)
                    self.logger.info(
                        f"✅ Автоматически исправлен никнейм для {applicant.display_name}: {original_nickname} → {fixed_nickname}"
                    )

                    # Создаем embed с информацией об исправлении
                    success_embed = discord.Embed(
                        title="✅ Никнейм автоматически исправлен!",
                        description=f"Ваш никнейм изменен на: **{fixed_nickname}**",
                        color=0x00FF00,
                    )

                    success_embed.add_field(
                        name="🔧 Применённые исправления:",
                        value="\n".join([f"• {fix}" for fix in fixes_applied]),
                        inline=False,
                    )

                    success_embed.add_field(
                        name="📋 Что дальше:",
                        value="Теперь бот автоматически перепроверит вашу заявку!",
                        inline=False,
                    )

                    await channel.send(embed=success_embed)

                    # Запускаем автоматическую перепроверку через 2 секунды
                    await asyncio.sleep(2)
                    await self.analyze_and_respond_to_application(channel, applicant)

                    return  # Прекращаем дальнейшую обработку

                except discord.Forbidden:
                    await channel.send(
                        "❌ У меня нет прав для изменения вашего никнейма. Измените его самостоятельно.",
                        ephemeral=True,
                    )
                    return
                except Exception as e:
                    self.logger.error(
                        f"❌ Ошибка автоисправления для {applicant.display_name}: {e}"
                    )
                    await channel.send(
                        "❌ Произошла ошибка при исправлении никнейма. Попробуйте изменить его самостоятельно.",
                        ephemeral=True,
                    )
                    return

            # Оцениваем никнейм на соответствие требованиям
            nickname_valid, nickname_errors = self.validate_nickname(current_nick)
            self.logger.info(
                f"Результат проверки никнейма: valid={nickname_valid}, errors={nickname_errors}"
            )

            # Оцениваем часы в Rust
            hours_valid, hours_errors = self.validate_rust_hours(rust_hours)
            self.logger.info(
                f"Результат проверки часов Rust: valid={hours_valid}, errors={hours_errors}"
            )

            # Объединяем результаты проверок
            overall_valid = nickname_valid and hours_valid
            overall_errors = nickname_errors + hours_errors

            # Формируем ответ в зависимости от результатов
            if overall_valid:
                # Заявка соответствует требованиям
                success_embed = discord.Embed(
                    title="✅ Заявка соответствует требованиям",
                    description=f"{applicant.mention}, ваша заявка полностью соответствует требованиям сервера!",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )

                success_embed.add_field(
                    name="📋 Статус",
                    value="Готова к рассмотрению модератором",
                    inline=False,
                )

                # Создаем кнопку перепроверки для успешных заявок тоже
                recheck_view = discord.ui.View(timeout=None)
                recheck_button = discord.ui.Button(
                    label="🔄 Проверить заявку ещё раз",
                    style=discord.ButtonStyle.green,
                    custom_id="recheck_application_3",
                )
                recheck_view.add_item(recheck_button)

                await channel.send(embed=success_embed, view=recheck_view)

                self.logger.info(
                    f"✅ Заявка {applicant.display_name} соответствует требованиям, ожидаем действий модератора"
                )

            else:
                # Заявка не соответствует требованиям
                rejection_embed = discord.Embed(
                    title="❌ Заявка не соответствует требованиям",
                    description=f"К сожалению, {applicant.mention}, ваша заявка не может быть одобрена.",
                    color=0xFF0000,
                    timestamp=datetime.now(timezone.utc),
                )

                # Добавляем информацию об ошибках
                error_message = "\n".join([f"• {error}" for error in overall_errors])
                rejection_embed.add_field(
                    name="📝 Найденные ошибки", value=error_message, inline=False
                )

                # Добавляем информацию о пользователе
                rejection_embed.add_field(
                    name="🎮 Steam", value=steam_url, inline=False
                )
                rejection_embed.add_field(
                    name="⏰ Rust (часов)", value=rust_hours, inline=True
                )
                rejection_embed.add_field(
                    name="Откуда узнали", value=how_found, inline=True
                )

                # Выводим текущий ник
                rejection_embed.add_field(
                    name="Текущий ник", value=current_nick, inline=False
                )

                # Добавляем кнопку перепроверки ПОСЛЕ отклонения
                recheck_view = RecheckApplicationView(applicant.id, steam_url)
                await channel.send(
                    "👆 **После исправления всех замечаний нажмите кнопку ниже:**",
                    view=recheck_view,
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при анализе заявки: {e}")
            await channel.send(
                "❌ Произошла ошибка при обработке вашей заявки. Попробуйте позже.",
                ephemeral=True,
            )

    @app_commands.command(
        name="auto_fix", description="Автоматически исправить никнейм"
    )
    @app_commands.describe(member="Участник для автоматического исправления никнейма")
    async def auto_fix_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Автоматическое исправление никнейма участника"""
        await interaction.response.defer()

        try:
            # Извлекаем информацию о пользователе
            original_nickname = member.display_name
            fixed_nickname, fixes_applied = auto_fix_nickname(original_nickname)

            if fixed_nickname != original_nickname:
                # Отправляем embed с предложением исправления
                fix_embed = discord.Embed(
                    title="🔧 Предлагается автоматическое исправление никнейма",
                    description=f"Текущий никнейм: **{original_nickname}**\nНовый никнейм: **{fixed_nickname}**",
                    color=0xFF9900,
                )

                fix_embed.add_field(
                    name="📝 Применённые исправления:",
                    value="\n".join([f"• {fix}" for fix in fixes_applied]),
                    inline=False,
                )

                # Добавляем кнопки для подтверждения или отклонения исправления
                fix_view = AutoFixConfirmationView(
                    member.id, original_nickname, fixed_nickname, fixes_applied
                )
                fix_message = await interaction.followup.send(
                    embed=fix_embed, view=fix_view
                )
                fix_view.message = fix_message

                self.logger.info(
                    f"Предложено автоисправление никнейма для {member.display_name}: {original_nickname} → {fixed_nickname}"
                )

            else:
                await interaction.followup.send(
                    "✅ Никнейм не требует исправлений.", ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /auto_fix: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )

    @app_commands.command(
        name="auto_fix", description="Автоматически исправить никнейм"
    )
    @app_commands.describe(member="Участник для автоматического исправления никнейма")
    async def auto_fix_command(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        """Автоматическое исправление никнейма участника"""
        await interaction.response.defer()

        try:
            # Извлекаем информацию о пользователе
            original_nickname = member.display_name
            fixed_nickname, fixes_applied = auto_fix_nickname(original_nickname)

            if fixed_nickname != original_nickname:
                # Отправляем embed с предложением исправления
                fix_embed = discord.Embed(
                    title="🔧 Предлагается автоматическое исправление никнейма",
                    description=f"Текущий никнейм: **{original_nickname}**\nНовый никнейм: **{fixed_nickname}**",
                    color=0xFF9900,
                )

                fix_embed.add_field(
                    name="📝 Применённые исправления:",
                    value="\n".join([f"• {fix}" for fix in fixes_applied]),
                    inline=False,
                )

                # Добавляем кнопки для подтверждения или отклонения исправления
                fix_view = AutoFixConfirmationView(
                    member.id, original_nickname, fixed_nickname, fixes_applied
                )
                fix_message = await interaction.followup.send(
                    embed=fix_embed, view=fix_view
                )
                fix_view.message = fix_message

                self.logger.info(
                    f"Предложено автоисправление никнейма для {member.display_name}: {original_nickname} → {fixed_nickname}"
                )

            else:
                await interaction.followup.send(
                    "✅ Никнейм не требует исправлений.", ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при выполнении команды /auto_fix: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при выполнении команды. Попробуйте позже.",
                ephemeral=True,
            )


class ConfirmApprovalView(discord.ui.View):
    def __init__(self, applicant: discord.Member, moderator: discord.Member):
        super().__init__(timeout=300)
        self.applicant = applicant
        self.moderator = moderator

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем, что только автор может взаимодействовать с кнопками"""
        if interaction.user.id != self.moderator.id:
            try:
                await interaction.response.send_message(
                    "❌ Только модератор, одобривший заявку, может подтвердить изменения.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                logger.warning(
                    f"⚠️ Interaction истек при проверке прав для {interaction.user.display_name}"
                )
            return False
        return True

    @discord.ui.button(label="✅ Да, одобрить", style=discord.ButtonStyle.success)
    async def confirm_approval(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Подтверждение одобрения заявки"""
        try:
            await interaction.response.defer()

            # Получаем роли
            novichok_role = discord.utils.get(
                interaction.guild.roles, id=config.NOVICHOK_ROLE_ID
            )
            prokhozhy_role = discord.utils.get(
                interaction.guild.roles, id=config.PROKHOZHY_ROLE_ID
            )

            if not novichok_role:
                await interaction.followup.send(
                    "❌ Роль 'Новичок' не найдена.", ephemeral=True
                )
                return

            self.logger.info(
                f"🎭 Начинаем выдачу ролей для {self.applicant.display_name}"
            )
            self.logger.info(
                f"🔍 Текущие роли: {[role.name for role in self.applicant.roles]}"
            )

            # Сначала убираем роль Прохожий если есть
            if prokhozhy_role and prokhozhy_role in self.applicant.roles:
                await self.applicant.remove_roles(
                    prokhozhy_role, reason="Замена на роль Новичок"
                )
                self.logger.info(
                    f"❌ Убрана роль '{prokhozhy_role.name}' у {self.applicant.display_name}"
                )

            # Затем выдаем роль Новичок
            if novichok_role not in self.applicant.roles:
                await self.applicant.add_roles(
                    novichok_role,
                    reason=f"Заявка одобрена модератором {interaction.user.display_name}",
                )
                self.logger.info(
                    f"✅ Выдана роль '{novichok_role.name}' пользователю {self.applicant.display_name}"
                )
            else:
                self.logger.info(
                    f"ℹ️ Роль '{novichok_role.name}' уже есть у {self.applicant.display_name}"
                )

            # Проверяем результат
            await self.applicant.reload()  # Обновляем данные пользователя
            updated_roles = [role.name for role in self.applicant.roles]
            self.logger.info(f"🔍 Роли после изменения: {updated_roles}")

            # Фиксируем никнейм
            try:
                current_nick = self.applicant.display_name
                await self.applicant.edit(
                    nick=current_nick,
                    reason=f"Фиксация никнейма после одобрения заявки",
                )
                self.logger.info(
                    f"✅ Никнейм '{current_nick}' зафиксирован для {self.applicant.display_name}"
                )
            except discord.Forbidden:
                self.logger.warning(
                    f"⚠️ Нет прав для фиксации никнейма у {self.applicant.display_name}"
                )
            except Exception as e:
                self.logger.error(f"❌ Ошибка фиксации нинейма: {e}")

            # Отправляем основное сообщение одобрения
            approval_embed = discord.Embed(
                title="✅ Заявка одобрена",
                description=f"Добро пожаловать {self.applicant.mention} в нашу Деревню! Ваша заявка одобрена и Вы теперь как <@&{novichok_role.id}> можете узнать про вайпы Деревни в разделе <#1186254344820113409> и создать <#1264874500693037197>.",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )
            approval_embed.add_field(
                name="👤 Новый участник",
                value=f"{self.applicant.display_name}\n{self.applicant.mention}",
                inline=True,
            )
            approval_embed.add_field(
                name="👮 Модератор", value=self.moderator.mention, inline=True
            )
            approval_embed.add_field(
                name="🎭 Роли изменены",
                value=f"✅ Добавлена: {novichok_role.name}"
                + (
                    f"\n❌ Убрана: {prokhozhy_role.name}"
                    if prokhozhy_role
                    and prokhozhy_role.name in [r.name for r in self.applicant.roles]
                    else ""
                ),
                inline=False,
            )

            await interaction.followup.send(embed=approval_embed)

            # Отправляем в личные дела
            personal_channel = interaction.guild.get_channel(config.PERSONAL_CHANNEL_ID)
            if personal_channel:
                # Получаем Steam URL из сохраненных данных (приоритет: кэш > БД > поиск)
                steam_url = "Не указано"
                hours_in_rust = "Не указано"

                try:
                    # 1. Пытаемся получить из кэша Steam
                    from handlers.tickets import steam_cache
                    cache_key = f"{interaction.channel.id}_{self.applicant.id}"
                    cached_data = steam_cache.get(cache_key)
                    if cached_data and isinstance(cached_data, dict):
                        if cached_data.get('steam_url'):
                            steam_url = cached_data['steam_url']
                            logger.info(f"🔍 Steam URL получен из кэша: {steam_url}")
                except Exception as e:
                    logger.error(f"❌ Ошибка получения из кэша: {e}")

                # 2. Если не найден в кэше, ищем в базе данных
                if steam_url == "Не указано":
                    try:
                        from handlers.tickets import get_steam_url_from_db
                        saved_steam_url = await get_steam_url_from_db(self.applicant.id)
                        if saved_steam_url:
                            steam_url = saved_steam_url
                            logger.info(f"🔍 Steam URL получен из БД: {steam_url}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка получения из БД: {e}")

                # 3. Последний шанс - ищем в истории канала (ускоренный поиск)
                if steam_url == "Не указано":
                    try:
                        async for message in interaction.channel.history(limit=30):
                            if message.embeds:
                                for embed in message.embeds:
                                    if embed.fields:
                                        for field in embed.fields:
                                            # Ищем Steam-профиль
                                            if field.name and "steam" in field.name.lower():
                                                if field.value and "steamcommunity.com" in field.value:
                                                    # Извлекаем URL с помощью регулярного выражения
                                                    import re
                                                    urls = re.findall(r'https://steamcommunity\.com/[^\s\)]+', field.value)
                                                    if urls:
                                                        steam_url = urls[0]
                                                        logger.info(f"🔍 Steam URL найден в истории: {steam_url}")
                                                        break

                                            # Ищем часы в Rust
                                            if field.name and ("часы" in field.name.lower() or "rust" in field.name.lower()):
                                                if field.value and field.value.strip() not in ["Не указано", "0", ""]:
                                                    hours_in_rust = field.value.strip()
                                                    logger.info(f"🎮 Часы Rust найдены в истории: {hours_in_rust}")
                            if steam_url != "Не указано":
                                break
                    except Exception as e:
                        logger.error(f"❌ Ошибка поиска в истории: {e}")

                logger.info(f"🔍 Итоговые данные для отчета - Steam URL: {steam_url}, Часы: {hours_in_rust}")

                # Создаем красивый embed отчет как в cogs/roles.py
                personal_embed = discord.Embed(
                    title="📝 Новый участник принят в Деревню",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )

                personal_embed.add_field(
                    name="👤 Игрок", value=f"{self.applicant.display_name}", inline=True
                )

                personal_embed.add_field(
                    name="👮 Модератор", value=f"@{self.moderator.display_name}", inline=True
                )

                personal_embed.add_field(
                    name="📋 Метод принятия", value="Тикет-система", inline=True
                )

                personal_embed.add_field(
                    name="👤 Личные данные",
                    value=f"**Discord:** {self.applicant.display_name}\n**ID:** {self.applicant.id}\n**Аккаунт создан:** {self.applicant.created_at.strftime('%d.%m.%Y %H:%M')}",
                    inline=False,
                )

                personal_embed.add_field(
                    name="🔗 Steam данные",
                    value=f"**Steam URL:** {steam_url}\n**Часы в Rust:** {hours_in_rust}",
                    inline=False,
                )

                personal_embed.add_field(
                    name="📋 Детали принятия",
                    value=f"**Дата принятия:** {datetime.now().strftime('%d.%m.%Y %H:%M')}\n**Роль выдана:** @Новичок\n**Изображение**\nЗаявка обработана • Тикет: {interaction.channel.name}•{datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    inline=False,
                )

                personal_embed.set_footer(
                    text=f"Принят через тикет-систему модератором {self.moderator.display_name}"
                )
                personal_embed.set_thumbnail(url=self.applicant.display_avatar.url)

                await personal_channel.send(embed=personal_embed)

            # Отправляем уведомление в модераторский канал
            mod_channel = mod_channel = interaction.guild.get_channel(config.MOD_CHANNEL_ID)
            if mod_channel:
                mod_embed = discord.Embed(
                    title="✅ Заявка одобрена",
                    description=f"**Игрок:** {self.applicant.mention}\n**Модератор:** {self.moderator.mention}",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )
                await mod_channel.send(embed=mod_embed)

            self.logger.info(
                f"✅ Заявка {self.applicant.display_name} одобрена модератором {self.moderator.display_name}"
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка подтверждения одобрения: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при одобрении заявки.", ephemeral=True
            )

    @discord.ui.button(
        label="✅ Одобрить заявку",
        style=discord.ButtonStyle.success,
        custom_id="approve_novichok",
        emoji="✅",
    )
    async def approve_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Одобрение заявки"""
        try:
            # Проверяем права модератора
            user_roles = [role.name for role in interaction.user.roles]
            allowed_roles = ["Житель", "Гражданин", "Администратор"]
            if not any(role in user_roles for role in allowed_roles):
                await interaction.response.send_message(
                    "❌ У вас нет прав для принятия заявок.", ephemeral=True
                )
                return

            applicant = interaction.guild.get_member(self.user_id)
            if not applicant:
                await interaction.response.send_message(
                    "❌ Заявитель не найден на сервере.", ephemeral=True
                )
                return
            await interaction.response.defer()

            # Получаем роли
            novichok_role = discord.utils.get(
                interaction.guild.roles, id=config.NOVICHOK_ROLE_ID
            )
            prokhozhy_role = discord.utils.get(
                interaction.guild.roles, id=config.PROKHOZHY_ROLE_ID
            )

            if not novichok_role:
                await interaction.response.send_message(
                    "❌ Роль 'Новичок' не найдена на сервере.", ephemeral=True
                )
                return

            # Подтверждение одобрения
            confirm_embed = discord.Embed(
                title="✅ Подтвердите одобрение заявки",
                description=f"Вы уверены, что хотите одобрить заявку игрока {applicant.mention}?",
                color=0x00FF00,
            )
            confirm_embed.add_field(
                name="👤 Игрок",
                value=f"{applicant.display_name}\n{applicant.mention}",
                inline=True,
            )

            # Показываем какие роли будут изменены
            role_changes = []
            if prokhozhy_role in applicant.roles:
                role_changes.append(f"❌ Убрать: {prokhozhy_role.name}")
            if novichok_role:
                role_changes.append(f"✅ Добавить: {novichok_role.name}")

            if role_changes:
                confirm_embed.add_field(
                    name="🎭 Изменения ролей",
                    value="\n".join(role_changes),
                    inline=False,
                )

            # Создаем view с кнопкой подтверждения
            confirm_view = ConfirmApprovalView(applicant, interaction.user)
            await interaction.followup.send(
                embed=confirm_embed, view=confirm_view, ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка при одобрении заявки: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при одобрении заявки. Попробуйте позже.",
                ephemeral=True,
            )


class ApplicationReviewView(discord.ui.View):
    def __init__(self, user_id: int, is_approved: bool = False):
        super().__init__(timeout=3600)  # 1 час
        self.user_id = user_id
        self.is_approved = is_approved

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем, что только автор может взаимодействовать с кнопками"""
        if interaction.user.id != self.user_id:
            try:
                await interaction.response.send_message(
                    "❌ Только автор заявки может использовать эти кнопки.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                pass
            return False
        return True

    @discord.ui.button(
        label="🔄 Проверить заявку ещё раз", style=discord.ButtonStyle.primary
    )
    async def recheck_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка повторной проверки заявки"""
        try:
            await interaction.response.defer()

            logger.info(
                f"🔄 Пользователь {interaction.user.display_name} запросил повторную проверку заявки"
            )

            await interaction.followup.send(
                "🔍 **Начинаю повторную проверку заявки...**\n\n"
                "Пожалуйста, подождите пока я перепроверю все данные.",
                ephemeral=True,
            )

            # Запускаем полную проверку заявки
            from handlers.novichok import process_application

            await process_application(interaction.user, interaction.channel)

        except Exception as e:
            logger.error(f"❌ Ошибка при повторной проверке заявки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при повторной проверке. Обратитесь к администрации.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="🔧 Исправить автоматически", style=discord.ButtonStyle.secondary
    )
    async def auto_fix_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка автоматического исправления никнейма"""
        try:
            await interaction.response.defer()

            # Логика автоматического исправления
            current_nickname = interaction.user.display_name

            # Автоматические исправления
            fixes_applied = []
            fixed_nickname = current_nickname

            # 1. Убираем недопустимые символы
            if re.search(r"[^a-zA-Z0-9а-яёА-ЯЁ_\-\s]", fixed_nickname):
                fixed_nickname = re.sub(
                    r"[^a-zA-Z0-9а-яёА-ЯЁ_\-\s]", "", fixed_nickname
                )
                fixes_applied.append("Удалены недопустимые символы")

            # 2. Убираем лишние пробелы
            if "  " in fixed_nickname:
                fixed_nickname = re.sub(r"\s+", " ", fixed_nickname).strip()
                fixes_applied.append("Убраны лишние пробелы")

            # 3. Проверяем длину (минимум 3 символа)
            if len(fixed_nickname) > 32:
                fixed_nickname = fixed_nickname[:32]
                fixes_applied.append("Обрезан до 32 символов")

            if len(fixed_nickname) < 3:
                # Если слишком короткий, предлагаем дополнить
                if len(current_nickname) > 0:
                    fixed_nickname = current_nickname[:1] + "Player"
                else:
                    fixed_nickname = "Player" + str(random.randint(100, 999))
                fixes_applied.append(
                    "Добавлены символы для достижения минимальной длины (3 символа)"
                )

            if not fixes_applied:
                await interaction.followup.send(
                    "✅ **Ваш никнейм уже соответствует требованиям!**\n"
                    "Возможно, проблема в другом (например, в Steam профиле).",
                    ephemeral=True,
                )
                return

            # Создаем новое view для подтверждения
            confirm_view = AutoFixConfirmationView(
                interaction.user.id, current_nickname, fixed_nickname, fixes_applied
            )

            embed = discord.Embed(title="🔧 Предложение автоматического исправления", color=0x3498DB)
            embed.add_field(
                name="📝 Текущий никнейм", value=f"`{current_nickname}`", inline=False
            )
            embed.add_field(
                name="✨ Исправленный никнейм",
                value=f"`{fixed_nickname}`",
                inline=False,
            )
            embed.add_field(
                name="🔧 Применённые исправления",
                value="\n".join([f"• {fix}" for fix in fixes_applied]),
                inline=False,
            )
            embed.add_field(
                name="ℹ️ Что дальше?",
                value="Подтвердите изменения или отмените и исправьте никнейм вручную.",
                inline=False,
            )

            await interaction.followup.send(
                embed=embed, view=confirm_view, ephemeral=True
            )

        except Exception as e:
            logger.error(f"❌ Ошибка в auto_fix_button: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при автоматическом исправлении.", ephemeral=True
            )

    @discord.ui.button(
        label="❌ Отклонить заявку", style=discord.ButtonStyle.danger
    )
    async def reject_application_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка отклонения заявки"""
        # Открываем модальное окно для ввода причины отклонения
        await interaction.response.send_modal(
            RejectReasonModal(self.user_id, "")
        )

    @discord.ui.button(
        label="✅ Одобрить заявку",
        style=discord.ButtonStyle.success,
        custom_id="approve_application_button",
    )
    async def approve_application_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка одобрения заявки"""
        try:
            # Получаем пользователя
            applicant = interaction.guild.get_member(self.user_id)
            if not applicant:
                await interaction.response.send_message(
                    "❌ Пользователь не найден на сервере.", ephemeral=True
                )
                return

            # Проверяем права модератора
            user_roles = [role.name for role in interaction.user.roles]
            admin_roles = ["Житель", "Гражданин", "Администратор"]
            if not any(role in user_roles for role in admin_roles):
                await interaction.response.send_message(
                    "❌ У вас нет прав для одобрения заявок.", ephemeral=True
                )
                return

            await interaction.response.defer()

            # Отправляем embed с подтверждением
            confirm_embed = discord.Embed(
                title="✅ Подтверждение одобрения заявки",
                description=f"Вы уверены, что хотите одобрить заявку игрока {applicant.mention}?",
                color=0x00FF00,
            )
            confirm_embed.add_field(
                name="👤 Игрок",
                value=f"{applicant.display_name}\n{applicant.mention}",
                inline=True,
            )

            # Показываем, какие роли будут изменены
            novichok_role = discord.utils.get(
                interaction.guild.roles, id=config.NEWBIE_ROLE_ID
            )
            prokhozhy_role = discord.utils.get(
                interaction.guild.roles, id=config.GUEST_ROLE_ID
            )

            role_changes = []
            if prokhozhy_role and prokhozhy_role in applicant.roles:
                role_changes.append(f"❌ Убрать: {prokhozhy_role.name}")
            if novichok_role:
                role_changes.append(f"✅ Добавить: {novichok_role.name}")

            if role_changes:
                confirm_embed.add_field(
                    name="🎭 Изменения ролей",
                    value="\n".join(role_changes),
                    inline=False,
                )

            # Создаем view с кнопкой подтверждения
            confirm_view = ConfirmApprovalView(applicant, interaction.user)
            await interaction.followup.send(
                embed=confirm_embed, view=confirm_view, ephemeral=True
            )

        except Exception as e:
            logger.error(f"❌ Ошибка при одобрении заявки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при одобрении заявки. Попробуйте позже.",
                ephemeral=True,
            )


class ErrorMessageView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем, что только автор может взаимодействовать с кнопками"""
        if interaction.user.id != self.user_id:
            try:
                await interaction.response.send_message(
                    "❌ Только автор заявки может использовать эти кнопки.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                logger.warning(
                    f"⚠️ Interaction истек при проверке прав для {interaction.user.display_name}"
                )
            return False
        return True

    @discord.ui.button(
        label="🔄 Попробовать еще раз",
        style=discord.ButtonStyle.primary,
        custom_id="retry_application",
    )
    async def retry_application(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка повторной отправки заявки"""
        try:
            await interaction.response.defer()

            logger.info(
                f"🔄 Пользователь {interaction.user.display_name} запросил повторную отправку заявки"
            )

            await interaction.followup.send(
                "🔍 **Начинаю повторную проверку заявки...**\n\n"
                "Пожалуйста, подождите пока я перепроверю все данные.",
                ephemeral=True,
            )

            # Запускаем полную проверку заявки
            from handlers.novichok import process_application

            await process_application(interaction.user, interaction.channel)

        except Exception as e:
            logger.error(f"❌ Ошибка при повторной проверке заявки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при повторной проверке. Обратитесь к администрации.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="🆘 Позвать Деревню на помощь",
        style=discord.ButtonStyle.secondary,
        emoji="🆘",
    )
    async def call_for_help(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Позвать на помощь"""
        try:
            await interaction.response.defer()

            # Получаем автора заявки
            author = interaction.guild.get_member(self.user_id)
            if not author:
                await interaction.edit_original_response(
                    content="❌ Автор заявки не найден на сервере."
                )
                return

            # Добавляем роль @гость автору заявки
            guest_role = interaction.guild.get_role(1208155640355229757)
            if guest_role and guest_role not in author.roles:
                await author.add_roles(guest_role, reason="Запрос помощи с заявкой")
                logger.info(
                    f"✅ Добавлена роль @гость пользователю {author.display_name}"
                )

            # Пингуем роли в чате
            ping_message = f"<@&1208155640355229757> <@&1176935405195636856> <@&945469407944118362> Просьба помочь {author.mention} с заявкой."

            await safe_send_message(interaction.channel, ping_message)
            await interaction.edit_original_response(
                content="✅ Призыв помощи отправлен!"
            )

            logger.info(f"🆘 Призыв помощи: {author.display_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка призыва помощи: {e}")
            try:
                await interaction.edit_original_response(
                    content="❌ Произошла ошибка при призыве помощи."
                )
            except:
                pass