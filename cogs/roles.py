import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timezone
from config import config
from utils.rate_limiter import (
    safe_send_message,
    safe_add_roles,
    safe_remove_roles,
    safe_edit_member,
    safe_send_followup,
)
from utils.discord_logger import log_to_channel, log_error, discord_logger
import asyncio
from typing import Dict

logger = logging.getLogger(__name__)

__all__ = ["RolesCog", "setup"]


class RolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def has_role(self, member: discord.Member, role_names: list[str]) -> bool:
        """Проверяет, есть ли у участника одна из указанных ролей"""
        return any(role.name in role_names for role in member.roles)

    async def find_user_application_data_enhanced(
        self, guild, user, current_channel=None
    ):
        """Ищет данные заявки ТОЛЬКО в текущем тикет-канале или в БД"""
        application_data = {
            "steam_url": "Не указано",
            "rust_hours": "Не указано",
            "how_found": "Не указано",
        }

        try:
            # ПРИОРИТЕТ 1: Проверяем сохраненные данные в базе данных
            try:
                from handlers.tickets import get_steam_url_from_db

                saved_steam_url = await get_steam_url_from_db(user.id)
                if saved_steam_url:
                    application_data["steam_url"] = saved_steam_url
                    logger.info(
                        f"🎯 Найдена сохраненная Steam-ссылка для {user.display_name}: {saved_steam_url}"
                    )

                    # Если нашли Steam-ссылку в БД, попробуем получить часы в Rust
                    try:
                        from handlers.steam_api import steam_client
                        from handlers.novichok import extract_steam_id_from_url

                        steam_id = extract_steam_id_from_url(saved_steam_url)
                        if steam_id:
                            steam_data = await steam_client.fetch_steam_data(steam_id)
                            if steam_data and steam_data.get("rust_playtime_minutes"):
                                minutes = steam_data["rust_playtime_minutes"]
                                hours = minutes // 60
                                application_data["rust_hours"] = f"{minutes} мин ({hours} ч)"
                                logger.info(
                                    f"🎮 Получены данные Rust для {user.display_name}: {minutes} мин ({hours} ч)"
                                )
                    except Exception as steam_error:
                        logger.warning(
                            f"⚠️ Не удалось получить данные Steam: {steam_error}"
                        )

                    return application_data  # Возвращаем данные из БД
            except ImportError:
                logger.warning("📋 Модуль базы данных недоступен")
            except Exception as db_error:
                logger.warning(f"⚠️ Ошибка получения данных из БД: {db_error}")

            # ПРИОРИТЕТ 2: Если команда выполнена в тикет-канале, ищем данные ТОЛЬКО в нем
            if current_channel and current_channel.name.startswith("new_"):
                logger.info(f"🔍 Поиск в текущем тикет-канале: {current_channel.name}")

                # Ищем embed от бота VLG | Помощник с заявкой (ПЕРВОЕ сообщение бота)
                async for message in current_channel.history(
                    limit=50, oldest_first=True
                ):
                    if (
                        message.embeds
                        and message.author.bot
                        and message.author.name == "VLG | Помощник"
                    ):
                        for embed in message.embeds:
                            # Проверяем, что это embed заявки пользователя
                            if embed.description and str(user.id) in embed.description:
                                logger.info(
                                    f"✅ Найден embed заявки для {user.display_name} в канале {current_channel.name}"
                                )

                                # Извлекаем Steam-ссылки из embed
                                from handlers.novichok import extract_steam_links

                                # Проверяем описание embed'а
                                if embed.description:
                                    steam_links = extract_steam_links(embed.description)
                                    if steam_links:
                                        application_data["steam_url"] = steam_links[0]
                                        logger.info(
                                            f"🔗 Найдена Steam-ссылка в описании embed'а: {steam_links[0]}"
                                        )
                                        return application_data

                                # Проверяем поля embed'а
                                if embed.fields:
                                    for field in embed.fields:
                                        field_name = (
                                            field.name.lower() if field.name else ""
                                        )
                                        field_value = (
                                            field.value.strip() if field.value else ""
                                        )

                                        if not field_value:
                                            continue

                                        # Определяем тип поля по ключевым словам
                                        if any(
                                            word in field_name
                                            for word in ["steam", "стим", "профиль"]
                                        ):
                                            if "steamcommunity.com" in field_value:
                                                application_data["steam_url"] = (
                                                    field_value
                                                )
                                                logger.info(
                                                    f"🔗 Найдена Steam-ссылка в поле '{field.name}': {field_value}"
                                                )
                                                return application_data
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
                                            application_data["rust_hours"] = field_value

                                # Если нашли embed заявки но без Steam-ссылки, прекращаем поиск
                                return application_data

        except Exception as e:
            logger.error(f"Ошибка поиска данных заявки для {user.display_name}: {e}")
            await log_error(e, f"Ошибка поиска данных заявки для {user.display_name}")

        logger.info(
            f"📊 Результат поиска для {user.display_name}: Steam={application_data['steam_url']}, Rust={application_data['rust_hours']}"
        )
        return application_data

    async def find_user_application_data(self, guild, user):
        """Ищет данные заявки пользователя ТОЛЬКО в базе данных"""
        application_data = {
            "steam_url": "Не указано",
            "rust_hours": "Не указано",
            "how_found": "Не указано",
        }

        try:
            # Проверяем ТОЛЬКО сохраненные данные в базе данных
            try:
                from handlers.tickets import get_steam_url_from_db

                saved_steam_url = await get_steam_url_from_db(user.id)
                if saved_steam_url:
                    application_data["steam_url"] = saved_steam_url
                    logger.info(
                        f"🎯 Найдена сохраненная Steam-ссылка для {user.display_name}: {saved_steam_url}"
                    )

                    # Если нашли Steam-ссылку в БД, попробуем получить часы в Rust
                    try:
                        from handlers.steam_api import steam_client
                        from handlers.novichok import extract_steam_id_from_url

                        steam_id = extract_steam_id_from_url(saved_steam_url)
                        if steam_id:
                            steam_data = await steam_client.fetch_steam_data(steam_id)
                            if steam_data and steam_data.get("rust_playtime_minutes"):
                                minutes = steam_data["rust_playtime_minutes"]
                                hours = minutes // 60
                                application_data["rust_hours"] = f"{minutes} мин ({hours} ч)"
                                logger.info(
                                    f"🎮 Получены данные Rust для {user.display_name}: {minutes} мин ({hours} ч)"
                                )
                    except Exception as steam_error:
                        logger.warning(
                            f"⚠️ Не удалось получить данные Steam: {steam_error}"
                        )

                    return application_data  # Возвращаем данные из БД
            except ImportError:
                logger.warning("📋 Модуль базы данных недоступен")
            except Exception as db_error:
                logger.warning(f"⚠️ Ошибка получения данных из БД: {db_error}")

        except Exception as e:
            logger.error(f"Ошибка поиска данных заявки для {user.display_name}: {e}")
            await log_error(e, f"Ошибка поиска данных заявки для {user.display_name}")

        logger.info(
            f"📊 Результат поиска для {user.display_name}: Steam={application_data['steam_url']}, Rust={application_data['rust_hours']}"
        )
        return application_data

    @app_commands.command(
        name="count_role",
        description="Подсчитать количество участников с определённой ролью",
    )
    @app_commands.describe(role="Роль для подсчёта участников")
    async def count_role(self, interaction: discord.Interaction, role: discord.Role):
        """Подсчитывает количество участников с указанной ролью"""
        logger.info(
            f"📊 Команда /count_role выполнена {interaction.user} для роли '{role.name}'"
        )
        await log_to_channel(
            "Команда",
            f"📊 Команда /count_role выполнена {interaction.user} для роли '{role.name}'",
        )

        # Подсчитываем участников с ролью
        members_with_role = [
            member for member in interaction.guild.members if role in member.roles
        ]
        count = len(members_with_role)

        # Формируем ответ
        if count == 0:
            response = f"🔍 Роль **{role.name}** не назначена ни одному участнику."
        elif count == 1:
            response = f"👤 Роль **{role.name}** имеет **1 участник**."
        elif 2 <= count <= 4:
            response = f"👥 Роль **{role.name}** имеют **{count} участника**."
        else:
            response = f"👥 Роль **{role.name}** имеют **{count} участников**."

        # Добавляем дополнительную информацию о роли
        response += f"\n\n📋 **Информация о роли:**"
        response += f"\n• ID роли: `{role.id}`"
        response += f"\n• Цвет: {role.colour}"
        response += f"\n• Позиция: {role.position}"
        response += f"\n• Упоминаемая: {'Да' if role.mentionable else 'Нет'}"
        response += f"\n• Отображается отдельно: {'Да' if role.hoist else 'Нет'}"

        await interaction.response.send_message(response, ephemeral=True)

        # Лог в канал логов
        guild = interaction.guild
        log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
        if log_channel:
            await safe_send_message(
                log_channel,
                f":bar_chart: **{interaction.user.display_name}** ({interaction.user.id}) использовал команду **/count_role** для роли **{role.name}** (результат: {count} участников).",
            )

    @app_commands.command(
        name="help", description="Показать полный список всех команд бота с описаниями"
    )
    async def help_command(self, interaction: discord.Interaction):
        """Показать полный справочник команд бота"""
        logger.info(f"📋 Команда /help выполнена пользователем {interaction.user}")

        try:
            await log_to_channel(
                "Команда",
                f"📋 Команда /help выполнена пользователем {interaction.user}",
            )
        except Exception as e:
            logger.error(f"Ошибка логирования: {e}")

        # Получаем роли пользователя для определения доступных команд
        user_roles = [role.name for role in interaction.user.roles]
        is_admin = any(role in user_roles for role in ["Администратор", "Офицер"])
        is_moderator = any(
            role in user_roles for role in ["Житель", "Гражданин", "Ополчение"]
        )

        # Создаем основной embed
        embed = discord.Embed(
            title="🤖 VLG | Помощник - Полный справочник команд",
            description="Все доступные команды Discord бота Деревни VLG с подробными описаниями:",
            color=0x2F3136,
        )

        # Основные команды для всех пользователей
        embed.add_field(
            name="📝 **Основные команды** (доступны всем)",
            value=(
                "`/help` - Показать этот справочник со всеми командами и их описаниями\n"
                "`/ping` - Проверить работу бота, скорость отклика и статистику\n"
                "`/entry` - Подать заявку на вступление в Деревню VLG (старая система)\n"
                "`/application` - Подать заявку через новую систему с модальными формами\n"
                "`/ticket` - Создать заявку на вступление в Деревню (основная команда)\n"
                "`/help_commands` - Альтернативная команда справки с кратким списком"
            ),
            inline=False,
        )

        # Игровые команды
        embed.add_field(
            name="🎮 **Игровые команды** (информация о серверах)",
            value=(
                "`/rust_servers` - Показать список серверов Rust Resort с командами подключения\n"
                "`/server_info` - Подробная информация о всех игровых серверах Деревни\n"
                "`/server_status` - Проверить онлайн статус серверов Rust в реальном времени\n"
                "`/wipe_info` - Информация о ближайших вайпах и расписании\n"
                "`/connect` - Получить команды для быстрого подключения к серверам"
            ),
            inline=False,
        )

        # ИИ команды
        embed.add_field(
            name="🧠 **ИИ-помощник** (умный помощник)",
            value=(
                "`/ask` - Задать вопрос ИИ-помощнику о Деревне VLG, правилах или игре\n"
                "`/ai_help` - Получить помощь от ИИ по любому игровому вопросу\n"
                "`/smart_reply` - Получить умный ответ от ИИ на сложные вопросы\n"
                "`/explain` - Попросить ИИ объяснить правила, механики или систему Деревни\n"
                "**Примечание:** ИИ также отвечает на упоминания бота в чатах"
            ),
            inline=False,
        )

        # Команды модерации (для Ополчения+)
        if is_moderator or is_admin:
            embed.add_field(
                name="🛡️ **Модерация заявок** (Ополчение, Житель, Гражданин)",
                value=(
                    "`/role` - Выдать роль Новичок участнику (переводит Прохожего в Новички)\n"
                    "`/check_nick` - Проверить никнейм участника на соответствие требованиям\n"
                    "`/info` - Показать подробную информацию о заявке участника\n"
                    "`/recheck` - Запустить повторную проверку заявки участника\n"
                    "`/clear_steam` - Очистить кэш Steam для участника (для перепроверки)\n"
                    "`/apply_fixes` - Применить автоматические исправления к никнейму\n"
                    "`/auto_fix` - Предложить автоматическое исправление никнейма участнику"
                ),
                inline=False,
            )

            embed.add_field(
                name="👑 **Управление ролями** (модераторы)",
                value=(
                    "`/give_role` - Выдать любую роль пользователю с указанием причины\n"
                    "`/remove_role` - Убрать роль у пользователя с указанием причины\n"
                    "`/role_info` - Показать подробную информацию о роли и её участниках\n"
                    "`/user_roles` - Показать все роли конкретного пользователя\n"
                    "`/count_role` - Подсчитать количество участников с определенной ролью\n"
                    "`/mass_role` - Массовая выдача или удаление ролей группе пользователей"
                ),
                inline=False,
            )

            embed.add_field(
                name="📊 **Статистика и мониторинг** (модераторы)",
                value=(
                    "`/ticket_stats` - Статистика обработки заявок за период\n"
                    "`/user_info` - Подробная информация о пользователе (активность)\n"
                    "`/bot_stats` - Статистика работы бота (команды, ошибки, производительность)\n"
                    "`/activity_stats` - Статистика активности пользователей на сервере\n"
                    "`/moderation_log` - Журнал модерационных действий"
                ),
                inline=False,
            )

        # Административные команды (только для админов)
        if is_admin:
            embed.add_field(
                name="⚙️ **Администрирование** (только Администраторы)",
                value=(
                    "`/admin_panel` - Открыть панель управления ботом с настройками\n"
                    "`/bot_settings` - Изменить настройки бота (каналы, параметры, роли)\n"
                    "`/sync_commands` - Пересинхронизировать slash-команды с Discord\n"
                    "`/reload_settings` - Перезагрузить настройки бота из файла конфигурации\n"
                    "`/clear_cache` - Очистить кэш Steam и других данных для оптимизации\n"
                    "`/restart_bot` - Перезапустить бота (только критические случаи)\n"
                    "`/backup_data` - Создать резервную копию данных бота"
                ),
                inline=False,
            )

        # Команды в тикетах (для авторов заявок)
        embed.add_field(
            name="🎫 **Команды в тикетах заявок** (для заявителей)",
            value=(
                "`готов` или `проверь` - Запросить повторную проверку заявки ботом\n"
                "`check` или `ready` - Альтернативные команды для перепроверки\n"
                "**Кнопки в тикетах:** Принять/Отклонить заявку, Удалить тикет, Перепроверить\n"
                "**Автофикс:** Бот автоматически предлагает исправления никнейма\n"
                "**Примечание:** Тикеты создаются автоматически при подаче заявки"
            ),
            inline=False,
        )

        # Дополнительная информация
        embed.add_field(
            name="ℹ️ **Дополнительная информация**",
            value=(
                "• **Упоминание бота** - Можете упомянуть @VLG | Помощник для получения помощи от ИИ\n"
                "• **Автоответы** - Бот автоматически отвечает на частые вопросы в тикетах\n"
                "• **Steam интеграция** - Автоматическая проверка Steam-профилей при заявках\n"
                "• **Логирование** - Все действия записываются в логи для контроля\n"
                "• **Кэширование** - Данные кэшируются для быстрой работы\n"
                f"• **Поддержка** - Обращайтесь к {', '.join(['<@&' + str(role_id) + '>' for role_id in [1178690166043963473, 1178689858251997204]])} при проблемах"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Запрошено пользователем {interaction.user.display_name} • Всего команд: 35+",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="Отправить информацию пользователю")
    @app_commands.describe(user="Пользователь, которому нужно отправить информацию")
    async def info(self, interaction: discord.Interaction, user: discord.Member):
        logger.info(
            f"ℹ️ Команда /info: {interaction.user} отправляет информацию пользователю {user}"
        )
        await log_to_channel(
            "Команда",
            f"ℹ️ Команда /info: {interaction.user} отправляет информацию пользователю {user}",
        )

        await interaction.response.defer()
        await safe_send_followup(
            interaction,
            f"Уважаемый {user.mention}, Вы не прочитали **требования** для вступления, которые написаны **выше вашей заявки**. "
            f"Не забудьте **переименовать свой никнейм** в нашем Дискорде, **открыть список игр** и **часы в Steam**, "
            f"а также **список друзей**. После этого **Ополчение Деревни** рассмотрит вашу заявку.",
        )

        # Лог в канал логов
        guild = interaction.guild
        log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
        if log_channel:
            await safe_send_message(
                log_channel,
                f":green_square: **{interaction.user.display_name}** ({interaction.user.id}) воспользовался командой **/info** для игрока {user.mention} ({user.id}).",
            )

        logger.info(f"✅ Информация успешно отправлена пользователю {user}")
        await log_to_channel(
            "Команда", f"✅ Информация успешно отправлена пользователю {user}"
        )

    @app_commands.command(
        name="text", description="Отправить текстовое сообщение в указанный канал"
    )
    @app_commands.describe(
        channel="Канал", message="Сообщение", embed="Отправить как Embed"
    )
    async def text(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
        embed: bool = False,
    ):
        logger.info(
            f"💬 Команда /text: {interaction.user} отправляет в #{channel.name}: {message[:50]}..."
        )
        await log_to_channel(
            "Команда",
            f"💬 Команда /text: {interaction.user} отправляет в #{channel.name}: {message[:50]}...",
        )

        await interaction.response.defer(ephemeral=True)
        try:
            # Обрабатываем экранированные символы
            content = (message
                      .replace("\\n", "\n")
                      .replace("\\r", "")
                      .replace("\\t", "\t"))

            if embed:
                await safe_send_message(
                    channel, embed=discord.Embed(description=content)
                )
                logger.info(f"✅ Embed-сообщение отправлено в #{channel.name}")
                await log_to_channel(
                    "Команда", f"✅ Embed-сообщение отправлено в #{channel.name}"
                )
            else:
                await safe_send_message(channel, content)
                logger.info(f"✅ Текстовое сообщение отправлено в #{channel.name}")
                await log_to_channel(
                    "Команда", f"✅ Текстовое сообщение отправлено в #{channel.name}"
                )

            await safe_send_followup(
                interaction,
                f"✅ Сообщение успешно отправлено в канал {channel.mention}",
                ephemeral=True,
            )

            # Лог в канал логов
            guild = interaction.guild
            log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
            if log_channel:
                message_type = "Embed" if embed else "Текстовое"
                await safe_send_message(
                    log_channel,
                    f":green_square: **{interaction.user.display_name}** ({interaction.user.id}) воспользовался командой **/text** и отправил {message_type} сообщение в канал {channel.mention}.",
                )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в #{channel.name}: {e}")
            await log_error(e, f"❌ Ошибка отправки в #{channel.name}")
            await safe_send_followup(
                interaction, f"❌ Ошибка при отправке сообщения: {e}", ephemeral=True
            )

    @app_commands.command(name="role", description="Выдать роль пользователю")
    @app_commands.describe(user="Кому выдать", role="Какую роль выдать")
    async def role(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        logger.info(
            f"🎭 Команда /role: {interaction.user} пытается выдать роль '{role.name}' пользователю {user}"
        )
        await log_to_channel(
            "Команда",
            f"🎭 Команда /role: {interaction.user} пытается выдать роль '{role.name}' пользователю {user}",
        )

        await interaction.response.defer()
        guild = interaction.guild
        author = interaction.user
        author_member = guild.get_member(author.id)
        log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
        notify_channel = guild.get_channel(config.NOTIFICATION_CHANNEL_ID)
        personal_channel = guild.get_channel(config.PERSONAL_CHANNEL_ID)

        # Логируем роли автора
        author_roles = [r.name for r in author_member.roles]
        logger.debug(f"🔍 Роли автора {author}: {author_roles}")

        # Логируем роли получателя
        user_roles = [r.name for r in user.roles]
        logger.debug(f"🔍 Роли получателя {user}: {user_roles}")

        # Военные роли
        if role.name in config.MILITARY_ROLES and self.has_role(
            author_member, config.EXCLUSIVE_ROLES
        ):
            logger.info(f"🪖 Попытка выдачи военной роли '{role.name}'")
            await log_to_channel(
                "Роль", f"🪖 Попытка выдачи военной роли '{role.name}'"
            )
            if self.has_role(user, config.ASSIGNABLE_ROLES):
                old_roles = [r for r in user.roles if r.name in config.MILITARY_ROLES]
                logger.info(
                    f"🔄 Удаляем старые военные роли: {[r.name for r in old_roles]}"
                )
                await log_to_channel(
                    "Роль",
                    f"🔄 Удаляем старые военные роли: {[r.name for r in old_roles]}",
                )
                for r in old_roles:
                    await safe_remove_roles(user, r)
                await safe_add_roles(user, role)
                logger.info(f"✅ Военная роль '{role.name}' выдана пользователю {user}")
                await log_to_channel(
                    "Роль", f"✅ Военная роль '{role.name}' выдана пользователю {user}"
                )

                # Ответ в канал где была выполнена команда
                await safe_send_followup(
                    interaction,
                    f"{author.mention} присвоил звание **{role.name}** ополченцу {user.mention}.",
                )

                # Уведомление в канал уведомлений
                if notify_channel:
                    await safe_send_message(
                        notify_channel,
                        f'{author.mention} присвоил звание **"{role.name}"** ополченцу {user.mention}.',
                    )

                # Детальный лог в канал логов
                if log_channel:
                    await safe_send_message(
                        log_channel,
                        f":green_square: **{author.display_name}** ({author.id}) воспользовался командой **/role** и выдал роль **{role.name}** игроку {user.mention} ({user.id}).",
                    )
                return
            logger.warning(
                f"⚠️ Отказ в выдаче военной роли: {user} не имеет подходящей базовой роли"
            )
            await log_to_channel(
                "Роль",
                f"⚠️ Отказ в выдаче военной роли: {user} не имеет подходящей базовой роли",
            )
            await safe_send_followup(
                interaction,
                "Роль можно выдать только тем, кто уже Гость, Житель или Гражданин.",
            )
            return

        # Новичок
        if role.name == "Новичок" and self.has_role(
            author_member, config.MODERATOR_ROLES
        ):
            logger.info(f"👋 Выдача роли 'Новичок' пользователю {user}")
            await log_to_channel(
                "Роль", f"👋 Выдача роли 'Новичок' пользователю {user}"
            )

            # Выдаем роль Новичок
            novichok_role = discord.utils.get(
                interaction.guild.roles, id=config.NEWBIE_ROLE_ID
            )

            if novichok_role:
                await safe_add_roles(user, novichok_role)
                old = discord.utils.get(user.roles, name="Прохожий")
                if old:
                    await safe_remove_roles(user, old)
                    logger.debug(f"🔄 Удалена роль 'Прохожий' у {user}")
                    await log_to_channel("Роль", f"🔄 Удалена роль 'Прохожий' у {user}")

                # Основной ответ в канал
                await safe_send_followup(
                    interaction,
                    f"Добро пожаловать {user.mention} в нашу Деревню. Ваша заявка одобрена и Вы теперь как <@&{novichok_role.id}> можете узнать про вайпы Деревни в разделе <#1186254344820113409> и создать <#1264874500693037197>.",
                )

                # Фиксируем никнейм после выдачи роли Новичок
                try:
                    current_nick = user.display_name
                    await safe_edit_member(
                        user,
                        nick=current_nick,
                        reason=f"Фиксация никнейма после получения роли {novichok_role.name}",
                    )
                    logger.info(
                        f"✅ Никнейм '{current_nick}' зафиксирован для {user.display_name} при выдаче роли через команду"
                    )
                    await log_to_channel(
                        "Роль",
                        f"✅ Никнейм '{current_nick}' зафиксирован для {user.display_name} при выдаче роли через команду",
                    )
                except discord.Forbidden:
                    logger.warning(
                        f"⚠️ Нет прав для фиксации никнейма у {user.display_name}"
                    )
                    await log_to_channel(
                        "Роль", f"⚠️ Нет прав для фиксации никнейма у {user.display_name}"
                    )
                    await safe_send_followup(
                        interaction,
                        "⚠️ Внимание: не удалось зафиксировать никнейм - у бота нет прав.",
                        ephemeral=True,
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка фиксации никнейма у {user.display_name}: {e}")
                    await log_error(e, f"❌ Ошибка фиксации никнейма у {user.display_name}")

                # Отправляем отчет в личные дела
                personal_channel = guild.get_channel(config.PERSONAL_CHANNEL_ID)
                if personal_channel:
                    try:
                        # Используем метод из novichok_actions для единообразия отчётов
                        from handlers.novichok_actions import TicketActionView
                        ticket_action = TicketActionView(0, "")  # Создаём экземпляр для доступа к методу
                        await ticket_action.send_personal_file_report(
                            personal_channel, user, interaction.user, "Команда /role", interaction.channel
                        )
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки отчёта в личные дела через /role: {e}")
                        # Fallback к старому методу
                        await self._send_legacy_personal_report(personal_channel, user, interaction)


                # Лог в канал логов
                if log_channel:
                    await safe_send_message(
                        log_channel,
                        f":green_square: **{author.display_name}** ({author.id}) воспользовался командой **/role** и выдал роль **{novichok_role.name}** игроку {user.mention} ({user.id}).",
                    )

                logger.info(f"✅ Роль 'Новичок' успешно выдана пользователю {user}")
                await log_to_channel(
                    "Роль", f"✅ Роль 'Новичок' успешно выдана пользователю {user}"
                )

                # Планируем автоматическое удаление тикета через 1 час, если это роль Новичок в тикет-канале
                if interaction.channel.name.startswith("new_"):
                    asyncio.create_task(
                        self._schedule_ticket_deletion_after_role(
                            interaction.channel, user, interaction.user
                        )
                    )
            else:
                logger.warning(
                    f"⚠️ Роль 'Новичок' с ID {config.NEWBIE_ROLE_ID} не найдена на сервере."
                )
                await log_to_channel(
                    "Роль",
                    f"⚠️ Роль 'Новичок' с ID {config.NEWBIE_ROLE_ID} не найдена на сервере.",
                )
                await safe_send_followup(
                    interaction,
                    "⚠️ Ошибка: Роль 'Новичок' не найдена на сервере. Пожалуйста, свяжитесь с администрацией.",
                    ephemeral=True,
                )
            return

        # Прохожий или Новичок
        if self.has_role(author_member, config.MODERATOR_ROLES):
            if role.name in config.ALLOWED_ROLES:
                logger.info(f"🔄 Смена базовой роли на '{role.name}' для {user}")
                await log_to_channel(
                    "Роль", f"🔄 Смена базовой роли на '{role.name}' для {user}"
                )
                opposite = "Новичок" if role.name == "Прохожий" else "Прохожий"
                await safe_remove_roles(
                    user, *[r for r in user.roles if r.name == opposite]
                )
                await safe_add_roles(user, role)

                # Разные сообщения для разных ролей
                if role.name == "Прохожий":
                    await safe_send_followup(
                        interaction,
                        f"Уважаемый {user.mention}, Вы теперь <@&{role.id}> и можете сами переименовать свой никнейм. Сделайте свой **ник по форме**. Например: **Terminator | Володя**",
                    )
                else:
                    await safe_send_followup(interaction, f"{user.mention} теперь <@&{role.id}>")

                # Лог в канал логов
                if log_channel:
                    await safe_send_message(
                        log_channel,
                        f":green_square: **{author.display_name}** ({author.id}) воспользовался командой **/role** и выдал роль **{role.name}** игроку {user.mention} ({user.id}).",
                    )
                logger.info(f"✅ Роль '{role.name}' выдана пользователю {user}")
                await log_to_channel(
                    "Роль", f"✅ Роль '{role.name}' выдана пользователю {user}"
                )

                # Логируем изменение роли в Discord канал
                try:
                    await discord_logger.log_role_change(
                        user=user,
                        role_name=role.name,
                        action="выдана",
                        moderator=interaction.user,
                    )
                except Exception as e:
                    logger.error(f"Ошибка логирования изменения роли: {e}")
                    await log_error(e, f"Ошибка логирования изменения роли")
                return
            else:
                logger.warning(
                    f"⚠️ Попытка выдать недопустимую роль '{role.name}' пользователем {author}"
                )
                await log_to_channel(
                    "Роль",
                    f"⚠️ Попытка выдать недопустимую роль '{role.name}' пользователем {author}",
                )
                await safe_send_followup(
                    interaction,
                    "Вы можете выдавать только роли 'Новичок' или 'Прохожий'",
                )
                return

        logger.warning(
            f"🚫 Отказано в доступе: {author} не имеет прав для выдачи ролей"
        )
        await log_to_channel(
            "Роль", f"🚫 Отказано в доступе: {author} не имеет прав для выдачи ролей"
        )
        await safe_send_followup(interaction, "У вас нет прав для этой команды.")

    async def cog_load(self):
        """Вызывается при загрузке модуля"""
        logger.info("✅ Roles модуль настроен")

    async def _schedule_ticket_deletion_after_role(self, channel, user, moderator):
        """Планирует удаление тикета через 1 час после выдачи роли Новичок"""
        try:
            # Ждем 1 час (3600 секунд)
            await asyncio.sleep(3600)

            # Проверяем, что канал все еще существует
            if channel and hasattr(channel, "guild") and channel.guild:
                try:
                    # Проверяем что канал действительно существует на сервере
                    test_channel = channel.guild.get_channel(channel.id)
                    if test_channel:
                        # Удаляем канал
                        await channel.delete(
                            reason=f"Автоматическое удаление через 1 час после выдачи роли Новичок пользователю {user.display_name} модератором {moderator.display_name}"
                        )

                        # Удаляем из кэша владельцев тикетов
                        from utils.ticket_state import ticket_owners, set_ticket_owner, del_ticket_owner, get_ticket_owner

                        if channel.id in ticket_owners:
                            del ticket_owners[channel.id]

                        logger.info(
                            f"🗑️ Автоматически удален тикет {channel.name} пользователя {user.display_name} через 1 час после выдачи роли"
                        )

                        # Отправляем уведомление в мод-канал
                        mod_channel = channel.guild.get_channel(config.MODERATION_CHANNEL_ID)
                        if mod_channel:
                            auto_delete_embed = discord.Embed(
                                title="🗑️ Автоматическое удаление тикета",
                                description=f"**Игрок:** {user.display_name}\n**Модератор:** {moderator.display_name}\n**Канал:** {channel.name}",
                                color=0x808080,
                                timestamp=datetime.now(timezone.utc),
                            )
                            auto_delete_embed.add_field(
                                name="⏰ Время",
                                value="Удален через 1 час после выдачи роли Новичок",
                                inline=False,
                            )
                            await mod_channel.send(embed=auto_delete_embed)
                    else:
                        logger.info(f"ℹ️ Тикет {channel.name} уже был удален вручную")
                except discord.NotFound:
                    logger.info(f"ℹ️ Тикет {channel.name} уже был удален")
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления тикета {channel.name}: {e}")
            else:
                logger.info(f"ℹ️ Тикет уже недоступен для удаления")

        except asyncio.CancelledError:
            logger.info(
                f"⚠️ Автоматическое удаление тикета {channel.name if channel else 'Unknown'} отменено"
            )
        except Exception as e:
            logger.error(f"❌ Критическая ошибка планирования удаления тикета: {e}")

    async def _send_legacy_personal_report(self, channel, user, interaction):
        """Fallback метод для отправки отчёта в личные дела"""
        try:
            steam_url = "Не указано"
            hours_in_rust = "Не указано"

            # Поиск Steam URL в истории канала
            try:
                async for message in interaction.channel.history(limit=30):
                    if message.embeds:
                        for embed in message.embeds:
                            if embed.fields:
                                for field in embed.fields:
                                    if field.name and "steam" in field.name.lower():
                                        if field.value and "steamcommunity.com" in field.value:
                                            import re
                                            urls = re.findall(r'https://steamcommunity\.com/[^\s\)]+', field.value)
                                            if urls:
                                                steam_url = urls[0]
                                                break
                                    if field.name and ("часы" in field.name.lower() or "rust" in field.name.lower()):
                                        if field.value and field.value.strip() not in ["Не указано", "0", ""]:
                                            hours_in_rust = field.value.strip()
                    if steam_url != "Не указано":
                        break
            except Exception as e:
                logger.error(f"❌ Ошибка поиска данных для fallback отчёта: {e}")

            # Получаем SteamID64
            steamid64 = "Не указано"
            if steam_url != "Не указано" and "steamcommunity.com" in steam_url:
                try:
                    from handlers.steam_api import get_steamid64_from_url
                    steamid64 = await get_steamid64_from_url(steam_url)
                    if not steamid64:
                        steamid64 = "Ошибка конвертации"
                except Exception as e:
                    logger.error(f"❌ Ошибка конвертации SteamID64 в fallback: {e}")
                    steamid64 = "Ошибка конвертации"

            # Создаем embed отчёт
            current_time = datetime.now()
            personal_embed = discord.Embed(
                title="📝 Новое личное дело",
                description="Участник принят в Деревню VLG",
                color=0x00FF00,
                timestamp=current_time
            )

            personal_embed.add_field(
                name="👤 Игрок",
                value=f"**Ник:** {user.display_name}\n**ID:** {user.id}\n**Упоминание:** {user.mention}",
                inline=True
            )

            personal_embed.add_field(
                name="👮 Модератор",
                value=f"**Ник:** {interaction.user.display_name}\n**Упоминание:** {interaction.user.mention}",
                inline=True
            )

            personal_embed.add_field(
                name="📋 Метод принятия",
                value="Команда /role",
                inline=True
            )

            personal_embed.add_field(
                name="👤 Личные данные Discord",
                value=f"**Discord:** {user.display_name}\n**Discord ID:** {user.id}\n**Аккаунт создан:** {user.created_at.strftime('%d.%m.%Y %H:%M')}",
                inline=False,
            )

            personal_embed.add_field(
                name="🔗 Steam данные",
                value=f"**Steam URL:** {steam_url}\n**SteamID64:** {steamid64}\n**Часы в Rust:** {hours_in_rust}",
                inline=False,
            )

            personal_embed.add_field(
                name="📋 Детали принятия",
                value=f"**Дата принятия:** {current_time.strftime('%d.%m.%Y %H:%M')}\n**Роль выдана:** @Новичок\n**Никнейм зафиксирован:** `{user.display_name}`\n**Канал:** {interaction.channel.mention}",
                inline=False,
            )

            personal_embed.set_footer(
                text=f"Принят через команду /role • {interaction.user.display_name} • {current_time.strftime('%d.%m.%Y %H:%M')}"
            )
            personal_embed.set_thumbnail(url=user.display_avatar.url)

            await channel.send(embed=personal_embed)
            logger.info(f"✅ Fallback отчёт в личные дела отправлен для {user.display_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка fallback отчёта в личные дела: {e}")

    async def _get_application_data_from_channel(
        self, channel: discord.TextChannel, user: discord.Member
    ) -> Dict[str, str]:
        """Получает данные заявки из тикет-канала"""
        application_data = {
            "steam_url": "Не указано",
            "rust_hours": "Не указано",
            "how_found": "Не указано",
        }

        try:
            # Ищем embed от бота с заявкой
            async for message in channel.history(limit=50):
                if message.embeds and message.author.bot:
                    for embed in message.embeds:
                        # Проверяем, что это embed с заявкой пользователя
                        if (
                            embed.description
                            and str(user.id) in embed.description
                        ) or (
                            embed.title
                            and user.display_name.lower() in embed.title.lower()
                        ):
                            # Извлекаем данные из полей embed
                            for field in embed.fields or []:
                                field_name = field.name.lower() if field.name else ""
                                field_value = field.value if field.value else ""

                                # Определяем тип поля
                                if "steam" in field_name:
                                    application_data["steam_url"] = field_value
                                elif "час" in field_name or "rust" in field_name:
                                    application_data["rust_hours"] = field_value
                                elif "узнали" in field_name or "друг" in field_name:
                                    application_data["how_found"] = field_value

                            break

        except Exception as e:
            logger.error(
                f"❌ Ошибка получения данных заявки из канала {channel.name}: {e}"
            )

        return application_data


async def setup(bot: commands.Bot):
    await bot.add_cog(RolesCog(bot))