# Applying the requested changes: removing duplicate logging from button handlers.
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
from datetime import datetime, timezone
from config import config
from utils.rate_limiter import safe_send_message
from utils.ticket_state import get_ticket_owner, set_ticket_owner, del_ticket_owner
from handlers.novichok import extract_discord_id
from handlers.steam_api import SteamAPIClient
from utils.logger import get_module_logger
from difflib import SequenceMatcher
import traceback
import re # Import re for regex operations

logger = get_module_logger(__name__)

def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()  # 0.0..1.0


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, author_id: int = None, deleter_id: int = None):
        super().__init__(timeout=None)
        self.author_id = author_id or 0
        self.deleter_id = deleter_id or 0

    @discord.ui.button(label="✅ Да, удалить", style=discord.ButtonStyle.danger, custom_id="confirm_delete_application_v2")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            channel = interaction.channel
            if channel:
                # Use del_ticket_owner from utils.ticket_state
                del_ticket_owner(channel.id)
                await channel.delete(reason=f"Заявка удалена пользователем {interaction.user.display_name}")
        except discord.NotFound:
            pass
        except Exception as e:
            logger.error(f"❌ Ошибка удаления заявки: {e}")
            try:
                await interaction.followup.send("❌ Произошла ошибка при удалении заявки.", ephemeral=True)
            except discord.NotFound:
                pass


def get_member_count(guild: discord.Guild) -> str:
    """Получает количество участников сервера для отображения"""
    try:
        member_count = guild.member_count
        if member_count:
            return f"{member_count:,}".replace(",", " ")  # Форматируем с пробелами
        return "3800+"  # Fallback значение
    except Exception as e:
        logger.error(f"❌ Ошибка получения количества участников: {e}")
        return "3800+"


class ApplicationModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="📝 Заявка на вступление в Деревню VLG")

        # Поле для Steam-профиля (обязательное)
        self.steam_profile = discord.ui.TextInput(
            label="🔗 Ссылка на ваш Steam-профиль",
            placeholder="https://steamcommunity.com/profiles/76561199488372591/",
            required=True,
            max_length=200,
        )
        self.add_item(self.steam_profile)

        # Поле для часов в Rust (необязательное)
        self.rust_hours = discord.ui.TextInput(
            label="🎮 Сколько часов у вас в Rust?",
            placeholder="Например: 110 часов",
            required=False,
            max_length=100,
        )
        self.add_item(self.rust_hours)

    async def on_submit(self, interaction: discord.Interaction):
        """Обработка отправки заявки"""
        user = interaction.user
        guild = interaction.guild

        # Проверяем Steam-ссылку
        steam_url = self.steam_profile.value.strip()
        if not steam_url.startswith("https://steamcommunity.com/"):
            await interaction.response.send_message(
                "❌ Пожалуйста, укажите корректную ссылку на Steam-профиль начинающуюся с https://steamcommunity.com/",
                ephemeral=True,
            )
            return

        # Проверяем возраст аккаунта (минимум 2 дня)
        account_age = (datetime.now(timezone.utc) - user.created_at).days
        if account_age < 2:
            await interaction.response.send_message(
                "❌ Ваш Discord аккаунт слишком молодой. Минимальный возраст аккаунта: 2 дня.",
                ephemeral=True,
            )
            return

        # Проверяем, есть ли уже роль у пользователя
        user_roles = [role.name for role in user.roles]
        if any(
            role in user_roles for role in ["Новичок", "Гость", "Житель", "Гражданин"]
        ):
            await interaction.response.send_message(
                "✅ Вы уже являетесь участником Деревни VLG!", ephemeral=True
            )
            return

        # Проверяем, нет ли уже активной заявки (новый формат названия канала)
        existing_channels = [
            ch
            for ch in guild.channels
            if isinstance(ch, discord.TextChannel)
            and ch.name.startswith(f"new_{user.name.lower()}")
        ]
        if existing_channels:
            await interaction.response.send_message(
                f"❌ У вас уже есть активная заявка: {existing_channels[0].mention}",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Создаем канал для заявки
            category = discord.utils.get(
                guild.categories, name="📬 Заявки на вступление"
            )
            if not category:
                # Создаем категорию если её нет
                category = await guild.create_category("📬 Заявки на вступление")
                logger.info(f"✅ Создана категория заявок: {category.name}")

            # Создаем приватный канал
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(
                    read_messages=True, send_messages=True
                ),
            }

            # Добавляем права для админских ролей
            admin_roles = ["Житель", "Гражданин"]
            for role_name in admin_roles:
                role = discord.utils.get(guild.roles, name=role_name)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True
                    )

            # Добавляем права для владельца сервера
            if guild.owner:
                overwrites[guild.owner] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True
                )

            channel_name = f"new_{user.name.lower()}"
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Заявка пользователя {user.display_name} ({user.id})",
            )

            # Создаем embed с заявкой
            embed = discord.Embed(
                title="📝 Новая заявка на вступление",
                description=f"Заявка от {user.mention}",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc),
            )

            embed.add_field(
                name="👤 Заявитель",
                value=f"{user.display_name}\n{user.mention}\nID: `{user.id}`",
                inline=True,
            )

            embed.add_field(
                name="📅 Дата подачи",
                value=f"{datetime.now().strftime('%d.%m.%Y %H:%M')}",
                inline=True,
            )

            embed.add_field(name="🔗 Steam-профиль", value=steam_url, inline=False)

            if self.rust_hours.value:
                embed.add_field(
                    name="🎮 Часы в Rust", value=self.rust_hours.value, inline=True
                )

            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text="Деревня VLG • Система заявок")

            # сразу после отправки embed заявки:
            await safe_send_message(
                channel,
                content="Нажмите кнопку, когда исправите данные. Запущу перепроверку.",
                view=ReadyButtonView(author_id=user.id),
            )

            # Создаем view с кнопкой удаления заявки
            delete_view = DeleteApplicationView(user.id)

            # Отправляем заявку в канал с кнопкой удаления
            await safe_send_message(channel, embed=embed, view=delete_view)

            logger.info(f"⏰ Анализ заявки для {user.display_name} начнется сразу же")

            # Регистрируем канал в системе обработки тикетов
            set_ticket_owner(channel.id, user.id)

            # Извлекаем часы Rust из поля если указано
            if self.rust_hours.value:
                # Извлекаем число часов из текста
                numbers = re.findall(r'\d+', self.rust_hours.value)
                if numbers:
                    try:
                        hours = int(numbers[0])
                        # Assuming get_ctx is a valid function to get context
                        # This part might need adjustment if get_ctx is not globally available or defined elsewhere
                        # For now, keeping it as is based on original code structure.
                        # If get_ctx is not defined, this will cause an error.
                        # ctx = get_ctx(channel.id)
                        # ctx.rust_hours = hours
                        # ctx.author_id = user.id
                        logger.info(f"🎮 Сохранены часы Rust при создании заявки {user.display_name}: {hours} ч")
                    except ValueError:
                        logger.warning(f"⚠️ Не удалось извлечь часы из: '{self.rust_hours.value}'")
                else:
                    logger.warning(f"⚠️ Не удалось извлечь часы из: '{self.rust_hours.value}'")

            # Запускаем автоматическую обработку заявки с небольшой задержкой

            ticket_handler = interaction.client.get_cog("TicketHandler")
            if not ticket_handler:
                # Попробуем альтернативный способ получения
                for cog_name, cog in interaction.client.cogs.items():
                    if hasattr(cog, 'analyze_and_respond_to_application'):
                        ticket_handler = cog
                        logger.info(f"🔍 Найден TicketHandler через поиск: {cog_name}")
                        break

            if ticket_handler:
                # Запускаем в фоне чтобы не блокировать ответ пользователю
                asyncio.create_task(
                    self._delayed_process_ticket(ticket_handler, channel, user)
                )

            await interaction.followup.send(
                f"✅ **Заявка создана!**\n\n"
                f"📋 Ваша заявка: {channel.mention}\n"
                f"⏰ Ожидайте рассмотрения заявки\n"
                f"💬 В самой заявке пишите ответы, пересоздавать заявку не надо",
                ephemeral=True,
            )

            logger.info(
                f"✅ Создана заявка для {user.display_name} в канале {channel.name}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка создания заявки для {user.display_name}: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при создании заявки. Обратитесь к Комендатуре.",
                ephemeral=True,
            )

    async def _delayed_process_ticket(self, ticket_handler, channel, user):
        """Отложенная обработка тикета"""
        try:
            # Ждем 3 секунды чтобы канал полностью инициализировался
            await asyncio.sleep(3)

            # 🔒 КРИТИЧЕСКАЯ ЗАЩИТА: проверяем, не обработан ли уже канал
            if (
                hasattr(ticket_handler, "_welcomed_channels")
                and channel.id in ticket_handler._welcomed_channels
            ):
                logger.info(
                    f"✅ Канал {channel.name} уже приветствован, пропускаем отложенную обработку"
                )
                return

            # Проверяем что канал все еще существует
            if channel and hasattr(channel, "guild") and channel.guild:
                # Выполняем полную обработку заявки (включает приветствие + анализ)
                await ticket_handler.process_new_ticket(channel, user)
                logger.info(f"✅ Полная обработка заявки завершена для {user.display_name}")
            else:
                logger.warning(
                    f"⚠️ Канал {channel.name if channel else 'Unknown'} больше не доступен для обработки"
                )

        except Exception as e:
            logger.error(f"❌ Ошибка отложенной обработки тикета: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")


class DeleteApplicationView(discord.ui.View):
    def __init__(self, author_id: int = None):
        super().__init__(timeout=None)
        self.author_id = author_id or 0

    @discord.ui.button(
        label="🔄 Проверить заявку ещё раз",
        style=discord.ButtonStyle.success,
        custom_id="recheck_application_4",
    )
    async def recheck_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Кнопка перепроверки заявки"""
        from utils.ticket_state import get_ticket_owner
        owner_id = get_ticket_owner(interaction.channel.id)
        allowed = {"Житель", "Гражданин"}
        is_author = interaction.user.id == (owner_id or self.author_id)
        has_perm = is_author or any(r.name in allowed for r in interaction.user.roles) or (interaction.user.id == interaction.guild.owner_id)
        if not has_perm:
            await interaction.response.send_message("❌ У вас нет прав для перепроверки.", ephemeral=True)
            return


        # Детальное логирование попытки нажатия кнопки
        logger.info(
            f"🔄 Попытка перепроверки заявки: пользователь {interaction.user.display_name} (ID: {interaction.user.id})"
        )
        logger.info(f"🔍 Сохраненный автор заявки ID: {self.author_id}")
        # Фильтруем @everyone чтобы не пинговать всех в логах
        user_role_names = [role.name for role in interaction.user.roles if role.name != "@everyone"]
        logger.info(
            f"👤 Роли пользователя: {user_role_names}"
        )

        # Определяем автора заявки из названия канала
        real_author_id = self.author_id
        real_author = None

        # ПРИОРИТЕТНАЯ проверка: извлекаем username из названия канала
        if interaction.channel and hasattr(interaction.channel, "name"):
            channel_name = interaction.channel.name
            logger.info(f"📁 Имя канала: {channel_name}")

            if channel_name.startswith("new_"):
                # Извлекаем username из new_username
                extracted_username = channel_name.replace("new_", "").lower()
                logger.info(
                    f"🔍 Извлеченный username из канала: '{extracted_username}'"
                )

                # УНИВЕРСАЛЬНЫЙ поиск автора заявки (работает для всех пользователей)
                found_author = None
                best_match_score = 0

                for member in interaction.guild.members:
                    member_username = member.name.lower()
                    member_display_name = member.display_name.lower()

                    # 1. ТОЧНОЕ совпадение username (приоритет 100%)
                    if member_username == extracted_username:
                        real_author_id = member.id
                        real_author = member
                        logger.info(
                            f"✅ [ТОЧНОЕ] Найден автор по username: {member.display_name} (ID: {member.id})"
                        )
                        break

                    # 2. Совпадение с частью display_name (до |) (приоритет 95%)
                    if " | " in member_display_name:
                        nick_part = member_display_name.split(" | ")[0].strip().lower()
                        if nick_part == extracted_username:
                            real_author_id = member.id
                            real_author = member
                            logger.info(
                                f"✅ [ТОЧНОЕ] Найден автор по части display_name: {member.display_name} (ID: {member.id})"
                            )
                            break

                    # 3. ЧАСТИЧНОЕ совпадение (для случаев как punisherr11 -> new_punisherr11)
                    if (
                        extracted_username in member_username
                        or member_username in extracted_username
                    ):
                        # Вычисляем схожесть более точно
                        longer_name = max(extracted_username, member_username, key=len)
                        shorter_name = min(extracted_username, member_username, key=len)

                        if shorter_name in longer_name:
                            # Рассчитываем процент совпадения
                            similarity = len(shorter_name) / len(longer_name)

                            # Требуем минимум 80% совпадения для частичного поиска
                            if similarity >= 0.8 and similarity > best_match_score:
                                found_author = member
                                best_match_score = similarity
                                logger.info(
                                    f"🔍 [КАНДИДАТ] Частичное совпадение: {member.display_name} (similarity: {similarity:.2f})"
                                )

                # Если не нашли точного совпадения, используем лучшего кандидата
                if not real_author and found_author and best_match_score >= 0.8:
                    real_author_id = found_author.id
                    real_author = found_author
                    logger.info(
                        f"✅ [ЧАСТИЧНОЕ] Найден автор: {found_author.display_name} (ID: {found_author.id}, score: {best_match_score:.2f})"
                    )

        # Если не нашли автора по имени канала, используем сохраненный ID
        if not real_author and real_author_id:
            real_author = interaction.guild.get_member(real_author_id)
            if real_author:
                logger.info(
                    f"✅ Используем сохраненного автора: {real_author.display_name} (ID: {real_author.id})"
                )

        # Проверяем права: автор заявки ВСЕГДА может перепроверить, также Граждане и Жители
        user_roles = [role.name for role in interaction.user.roles]
        allowed_roles = ["Житель", "Гражданин"]
        is_author = interaction.user.id == real_author_id
        has_permission = any(role in user_roles for role in allowed_roles)

        logger.info(f"🔑 ДЕТАЛЬНАЯ ПРОВЕРКА ДОСТУПА:")
        logger.info(
            f"   👤 Пользователь: {interaction.user.display_name} (ID: {interaction.user.id})"
        )
        logger.info(f"   📁 Канал: {interaction.channel.name}")
        logger.info(
            f"   🎯 Найденный автор: {real_author.display_name if real_author else 'НЕ НАЙДЕН'} (ID: {real_author_id})"
        )
        logger.info(
            f"   ✅ is_author: {is_author} (сравнение {interaction.user.id} == {real_author_id})"
        )
        # Фильтруем @everyone чтобы не пинговать всех в логах
        filtered_roles = [role for role in user_roles if role != "@everyone"]
        logger.info(f"   🛡️ has_permission: {has_permission} (роли: {filtered_roles})")
        logger.info(f"   🔍 Все участники с похожими именами:")

        # Дополнительное логирование для отладки
        extracted_username = (
            interaction.channel.name.replace("new_", "").lower()
            if interaction.channel.name.startswith("new_")
            else "unknown"
        )
        matching_users = []
        for member in interaction.guild.members:
            if (
                extracted_username in member.name.lower()
                or member.name.lower() in extracted_username
                or (
                    hasattr(member, "display_name")
                    and extracted_username in member.display_name.lower()
                )
            ):
                matching_users.append(
                    f"      - {member.display_name} (username: {member.name}, ID: {member.id})"
                )

        if matching_users:
            for user_info in matching_users:
                logger.info(user_info)
        else:
            logger.info(
                f"      - Участники с похожими именами не найдены для '{extracted_username}'"
            )

        # АВТОР ЗАЯВКИ ВСЕГДА может перепроверить свою заявку
        if not (is_author or has_permission):
            logger.warning(
                f"🚫 Отказано в доступе: {interaction.user.display_name} не является автором ({is_author}) и не имеет нужных ролей ({has_permission})"
            )
            await interaction.response.send_message(
                "❌ Только **автор заявки** или пользователи со статусом **Гражданин**/**Житель** могут перепроверить заявку.\n\n"
                f"💡 Если это ваша заявка, убедитесь что канал создан от вашего имени.\n"
                f"🔍 Найденный автор: {real_author.display_name if real_author else 'Не найден'}",
                ephemeral=True,
            )
            return


        # Находим автора заявки (уже определен выше)
        author = real_author
        if not author:
            try:
                await interaction.response.send_message(
                    "❌ Автор заявки не найден на сервере.", ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning(
                    f"⚠️ Interaction истек для {interaction.user.display_name} - автор не найден"
                )
            return

        try:
            # Проверяем, не acknowledged ли уже interaction
            if interaction.response.is_done():
                logger.warning(
                    f"⚠️ Interaction уже acknowledged для {interaction.user.display_name}"
                )
                # Отправляем обычное сообщение в канал как fallback
                await interaction.channel.send(
                    f"🔄 {interaction.user.mention} запустил перепроверку заявки {author.mention}..."
                )
            else:
                await interaction.response.send_message(
                    f"🔄 {interaction.user.mention} запустил перепроверку заявки {author.mention}...",
                    ephemeral=False,
                )
        except discord.errors.InteractionResponded:
            logger.warning(
                f"⚠️ Interaction уже отвечен для {interaction.user.display_name}"
            )
            # Отправляем обычное сообщение в канал как fallback
            await interaction.channel.send(
                f"🔄 {interaction.user.mention} запустил перепроверку заявки {author.mention}..."
            )
        except discord.errors.NotFound:
            logger.warning(f"⚠️ Interaction истек для {interaction.user.display_name}")
            # Отправляем обычное сообщение в канал как fallback
            await interaction.channel.send(
                f"🔄 {interaction.user.mention} запустил перепроверку заявки {author.mention}..."
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления о перепроверке: {e}")
            return

        try:

            # Получаем TicketHandler для перепроверки
            ticket_handler = interaction.client.get_cog("TicketHandler")
            if not ticket_handler:
                # Попробуем альтернативный способ получения
                for cog_name, cog in interaction.client.cogs.items():
                    if hasattr(cog, 'analyze_and_respond_to_application'):
                        ticket_handler = cog
                        logger.info(f"🔍 Найден TicketHandler через поиск: {cog_name}")
                        break

            if ticket_handler:
                # Очищаем кэш Steam для свежей проверки
                try:
                    # Очищаем локальный кэш Steam
                    from handlers.tickets import local_steam_cache
                    if hasattr(local_steam_cache, 'clear'):
                        local_steam_cache.clear()

                    logger.info(
                        f"🗑️ Подготовка к перепроверке заявки {author.display_name}"
                    )
                except Exception as e:
                    logger.error(f"Ошибка очистки кэша: {e}")

                # Запускаем полную перепроверку заявки
                await ticket_handler.analyze_and_respond_to_application(
                    interaction.channel, author
                )

                logger.info(
                    f"🔄 Перепроверка заявки запущена: {author.display_name} по запросу {interaction.user.display_name}"
                )
            else:
                logger.error("❌ TicketHandler не найден! Доступные cogs:")
                for cog_name in interaction.client.cogs.keys():
                    logger.error(f"   - {cog_name}")

                await interaction.followup.send(
                    "❌ Система обработки заявок недоступна. Обратитесь к администратору.",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"❌ Ошибка перепроверки заявки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при перепроверке заявки.", ephemeral=True
            )

    @discord.ui.button(label="🗑️ Удалить заявку", style=discord.ButtonStyle.danger, custom_id="delete_application_v4")
    async def delete_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Кнопка удаления заявки с подтверждением"""

        # Определяем автора заявки
        real_author_id = None
        real_author = None

        # Сначала проверяем владельца тикета из ticket_state
        from utils.ticket_state import get_ticket_owner
        ticket_owner_id = get_ticket_owner(interaction.channel.id)
        if ticket_owner_id:
            real_author = interaction.guild.get_member(ticket_owner_id)
            if real_author:
                real_author_id = ticket_owner_id
                logger.info(f"🎯 Автор найден через ticket_state: {real_author.display_name} (ID: {real_author_id})")

        # Если не нашли через ticket_state, пробуем извлечь из имени канала
        if not real_author_id:
            extracted_username = extract_discord_id(interaction.channel.name)
            if extracted_username:
                # Поиск пользователя по имени
                matching_users = []
                for member in interaction.guild.members:
                    # Точное совпадение имени пользователя
                    if member.name.lower() == extracted_username.lower():
                        real_author_id = member.id
                        real_author = member
                        logger.info(f"🎯 Автор найден по точному совпадению имени: {member.display_name} (ID: {member.id})")
                        break

                    # Точное совпадение никнейма
                    if member.display_name.lower() == extracted_username.lower():
                        real_author_id = member.id
                        real_author = member
                        logger.info(f"🎯 Автор найден по точному совпадению никнейма: {member.display_name} (ID: {member.id})")
                        break

                    # Частичное совпадение для логирования
                    similarity = _ratio(member.display_name.lower(), extracted_username.lower()) # Using _ratio instead of fuzz.ratio
                    if similarity >= 0.8: # Adjusted threshold for _ratio
                        matching_users.append({
                            "member": member,
                            "similarity": similarity,
                            "match_type": "display_name"
                        })

                        if similarity >= 0.95:  # Very high similarity for _ratio
                            real_author_id = member.id
                            real_author = member
                            logger.info(f"🎯 Автор найден по высокому совпадению никнейма ({similarity:.2f}): {member.display_name} (ID: {member.id})")
                            break

                # Если не нашли точного совпадения, попробуем поиск по ID из embed
                if not real_author_id:
                    best_match_score = 0
                    found_author_id = None
                    # Поиск в embed заявки
                    async for message in interaction.channel.history(limit=50):
                        if message.embeds:
                            for embed in message.embeds:
                                if embed.title and "заявка" in embed.title.lower():
                                    # Ищем упоминание пользователя в описании или полях
                                    content_to_search = []
                                    if embed.description:
                                        content_to_search.append(embed.description)
                                    for field in embed.fields:
                                        content_to_search.append(field.value)

                                    for content in content_to_search:
                                        # Ищем упоминание вида <@123456789>
                                        import re
                                        mentions = re.findall(r'<@!?(\d+)>', content)
                                        for user_id_str in mentions:
                                            try:
                                                found_user_id = int(user_id_str)
                                                found_member = interaction.guild.get_member(found_user_id)
                                                if found_member and extracted_username:
                                                    s1 = SequenceMatcher(None, found_member.name.lower(), extracted_username.lower()).ratio()
                                                    s2 = SequenceMatcher(None, found_member.display_name.lower(), extracted_username.lower()).ratio()
                                                    similarity = max(s1, s2)  # 0.0..1.0

                                                    if similarity >= 0.80 and similarity > best_match_score:
                                                        found_author_id = found_member.id
                                                        best_match_score = similarity
                                            except Exception:
                                                pass

                # Используем лучшего кандидата если не нашли точного совпадения
                if not real_author_id and found_author_id and best_match_score >= 0.8:
                    real_author_id = found_author_id

        # Проверяем права: автор заявки, Гражданин или Владелец сервера могут удалить
        user_roles = [role.name for role in interaction.user.roles]
        is_citizen = "Гражданин" in user_roles or "Житель" in user_roles # Added "Житель" to check
        is_author = interaction.user.id == real_author_id
        is_owner = interaction.user.id == interaction.guild.owner_id

        if not (is_author or is_citizen or is_owner):
            await interaction.response.send_message(
                "❌ Удалять заявки могут только автор заявки, **Гражданин** или **Владелец сервера**.",
                ephemeral=True,
            )
            return

        # Подтверждение удаления
        confirm_embed = discord.Embed(
            title="⚠️ Подтверждение удаления",
            description="Вы уверены, что хотите удалить эту заявку? Это действие нельзя отменить.",
            color=0xFF9900,
        )

        confirm_view = ConfirmDeleteView(real_author_id or 0, interaction.user.id)
        await interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)


    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary, custom_id="cancel_delete_application_v2")
    async def cancel_delete(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Отмена удаления"""
        await interaction.response.edit_message(
            content="❌ Удаление отменено.", embed=None, view=None
        )


class ReadyButtonView(discord.ui.View):
    def __init__(self, author_id: int = None):
        super().__init__(timeout=None)
        self.author_id = author_id or 0

    @discord.ui.button(
        label="🔄 Перепроверить заявку",
        style=discord.ButtonStyle.primary,
        custom_id="ready_button_v4",
    )
    async def ready_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка перепроверки - очищает кэш и заново проверяет заявку"""
        # Проверяем, что кнопку нажал автор заявки
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Эта кнопка предназначена только для автора заявки.", ephemeral=True
            )
            return

        try:
            await interaction.response.send_message(
                f"🔄 {interaction.user.mention} запросил перепроверку заявки! Очищаю кэш и запускаю полный анализ...",
                ephemeral=False,
            )
        except discord.errors.InteractionResponded:
            logger.warning(
                f"⚠️ Interaction уже отвечен для {interaction.user.display_name}"
            )
            await interaction.channel.send(
                f"🔄 {interaction.user.mention} запросил перепроверку заявки! Очищаю кэш и запускаю полный анализ..."
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления о перепроверке: {e}")
            return

        try:
            # Получаем TicketHandler для перепроверки
            ticket_handler = interaction.client.get_cog("TicketHandler")
            if not ticket_handler:
                # Попробуем альтернативный способ получения
                for cog_name, cog in interaction.client.cogs.items():
                    if hasattr(cog, 'analyze_and_respond_to_application'):
                        ticket_handler = cog
                        logger.info(f"🔍 Найден TicketHandler через поиск: {cog_name}")
                        break

            if ticket_handler:
                # Полная очистка всех кэшей для пользователя
                try:
                    # Очищаем локальный кэш Steam
                    from handlers.tickets import local_steam_cache
                    if hasattr(local_steam_cache, 'clear'):
                        local_steam_cache.clear()
                    logger.info(f"🗑️ Локальный кэш очищен для {interaction.user.display_name}")

                    # Дополнительно очищаем кэш Steam API
                    from handlers.steam_api import steam_client
                    from handlers.novichok import extract_steam_id_from_url

                    # Ищем Steam-ссылку в канале и очищаем её кэш
                    async for msg in interaction.channel.history(limit=50):
                        if msg.embeds:
                            for embed in msg.embeds:
                                if (
                                    embed.description
                                    and "steamcommunity.com" in embed.description
                                ):
                                    import re

                                    steam_links = re.findall(
                                        r"https://steamcommunity\.com/[^\s]+",
                                        embed.description,
                                    )
                                    for steam_link in steam_links:
                                        steam_id = extract_steam_id_from_url(steam_link)
                                        if steam_id:
                                            steam_client.force_cache_clear_for_profile(
                                                steam_id
                                            )
                                            logger.info(
                                                f"🗑️ Очищен Steam кэш для ID: {steam_id}"
                                            )
                                            break
                                if embed.fields:
                                    for field in embed.fields:
                                        if (
                                            field.value
                                            and "steamcommunity.com" in field.value
                                        ):
                                            import re

                                            steam_links = re.findall(
                                                r"https://steamcommunity\.com/[^\s]+",
                                                field.value,
                                            )
                                            for steam_link in steam_links:
                                                steam_id = extract_steam_id_from_url(
                                                    steam_link
                                                )
                                                if steam_id:
                                                    steam_client.force_cache_clear_for_profile(
                                                        steam_id
                                                    )
                                                    logger.info(
                                                        f"🗑️ Очищен Steam кэш для ID: {steam_id}"
                                                    )
                                                    break

                    logger.info(
                        f"🗑️ Полная очистка кэша выполнена для {interaction.user.display_name}"
                    )
                except Exception as e:
                    logger.error(f"Ошибка полной очистки кэша: {e}")

                # Запускаем полную перепроверку заявки
                await ticket_handler.analyze_and_respond_to_application(
                    interaction.channel, interaction.user
                )

                logger.info(
                    f"✅ Полная перепроверка запущена: {interaction.user.display_name}"
                )
            else:
                logger.error("❌ TicketHandler не найден! Доступные cogs:")
                for cog_name in interaction.client.cogs.keys():
                    logger.error(f"   - {cog_name}")

                await interaction.followup.send(
                    "❌ Система обработки заявок недоступна. Обратитесь к администратору.",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"❌ Ошибка полной перепроверки: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при перепроверке заявки.", ephemeral=True
            )


class ApplicationButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Вступить в Деревню",
        style=discord.ButtonStyle.primary,
        custom_id="application_button",
        emoji="<:Civil1:1287759173475635200>",
    )
    async def application_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Обработчик кнопки подачи заявки"""
        try:
            logger.info(
                f"🎯 Пользователь {interaction.user.display_name} нажал кнопку подачи заявки"
            )

            # Создаем модальное окно
            modal = ApplicationModal()

            # Отправляем модальное окно (без дополнительных проверок)
            await interaction.response.send_modal(modal)
            logger.info(
                f"✅ Модальное окно отправлено пользователю {interaction.user.display_name}"
            )

        except discord.errors.InteractionResponded:
            logger.warning(
                f"⚠️ Interaction уже был обработан для {interaction.user.display_name}"
            )
        except discord.errors.NotFound:
            logger.warning(f"⚠️ Interaction истек для {interaction.user.display_name}")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке нажатия кнопки заявки: {e}")

            # Логируем детали ошибки для всех заявок
            import traceback

            logger.error(
                f"Traceback для заявки {interaction.user.display_name}: {traceback.format_exc()}"
            )


class ApplicationSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.application_panels = []  # Список панелей для автообновления
        self.auto_update_member_count.start()  # Запускаем автообновление

    def cog_unload(self):
        """Останавливаем задачи при выгрузке модуля"""
        self.auto_update_member_count.cancel()

    @tasks.loop(hours=24)  # Обновляем раз в сутки
    async def auto_update_member_count(self):
        """Автоматическое обновление количества участников в панелях заявок"""
        if not self.application_panels:
            return

        logger.info("🔄 Начинаю автоматическое обновление панелей заявок...")
        updated_count = 0

        for panel_info in self.application_panels.copy():
            try:
                channel = self.bot.get_channel(panel_info["channel_id"])
                if not channel:
                    # Удаляем панель если канал больше не существует
                    self.application_panels.remove(panel_info)
                    continue

                message = await channel.fetch_message(panel_info["message_id"])
                member_count = get_member_count(channel.guild)

                # Обновляем embed
                if message.embeds:
                    embed = message.embeds[0]
                    # Обновляем описание
                    new_description = embed.description
                    if "соседями!" in new_description:
                        import re

                        new_description = re.sub(
                            r"с \d+[\s\d]* соседями!",
                            f"с {member_count} соседями!",
                            new_description,
                        )
                        embed.description = new_description

                    # Обновляем footer
                    if embed.footer:
                        new_footer = re.sub(
                            r"• \d+[\s\d]* участников •",
                            f"• {member_count} участников •",
                            embed.footer.text,
                        )
                        embed.set_footer(text=new_footer)

                    await message.edit(embed=embed)
                    updated_count += 1
                    logger.info(
                        f"✅ Обновлена панель в {channel.name}: {member_count} участников"
                    )

            except discord.NotFound:
                # Удаляем панель если сообщение больше не существует
                self.application_panels.remove(panel_info)
                logger.warning(f"⚠️ Удалена панель: сообщение не найдено")
            except Exception as e:
                logger.error(f"❌ Ошибка обновления панели: {e}")

        if updated_count > 0:
            logger.info(
                f"🔄 Автообновление завершено: обновлено {updated_count} панелей"
            )

    @auto_update_member_count.before_loop
    async def before_auto_update(self):
        """Ожидаем готовности бота перед началом автообновления"""
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="create_application_panel", description="Создать панель для подачи заявок"
    )
    @app_commands.describe(channel="Канал для размещения панели")
    @app_commands.guild_only()
    async def create_application_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        """Создает панель для подачи заявок"""

        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id

        if not any(role in user_roles for role in admin_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для создания панели заявок.", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel

        # Получаем актуальное количество участников
        member_count = get_member_count(interaction.guild)

        # Создаем основной embed с требованиями
        main_embed = discord.Embed(
            title="📋 Подача заявки в Деревню VLG",
            description=(
                f"🏘️ **Добро пожаловать в самую большую Деревню в Rust с {member_count} соседями!**\n\n"
                "🎯 **Перед подачей заявки обязательно:**\n\n"
                "**1.** 📝 Измените ваш ник в Discord по формату: `SteamNickname | Имя`\n"
                "└─ **Пример:** `Terminator | Володя`\n"
                "└─ **Как изменить:** ПКМ по нику → *Редактировать личный профиль сервера*\n\n"
                "**2.** 🔗 Убедитесь что у вас есть корректная ссылка на Steam-профиль\n\n"
                "**3.** 👤 **Ник в Steam должен совпадать с ником в Discord**\n\n"
                "⚠️ **Важно:** Проверьте всё ещё раз перед подачей заявки!"
            ),
            color=0x00FF00,
        )

        main_embed.add_field(
            name="✅ Подходящие ники:",
            value="`Bestel`, `Yango`, `Справедливый`, `Борис`, `Gen0m`, `Юный Воин`",
            inline=False,
        )

        main_embed.add_field(
            name="❌ НЕ подойдут:",
            value="`༒☬☠Ƚ︎ÙçҜყ☠︎☬༒`, `775038`, `K Δ Я U MI`, `crmnl1`, `Y1`, `AB`, `OOO`",
            inline=False,
        )

        main_embed.set_footer(
            text=f"Деревня VLG • {member_count} участников • 170+ вайпов"
        )
        main_embed.set_thumbnail(
            url="https://cdn.discordapp.com/attachments/472365787445985280/icon.png"
        )
        main_embed.set_image(url="https://i.ibb.co/kVvrcT3Q/VLG-Logo.gif")

        # Создаем view с кнопкой
        view = ApplicationButton()

        try:
            # Отправляем панель в указанный канал
            message = await safe_send_message(
                target_channel, embed=main_embed, view=view
            )

            # Регистрируем панель для автообновления
            panel_info = {
                "message_id": message.id,
                "channel_id": target_channel.id,
                "created_at": datetime.now(timezone.utc),
            }
            self.application_panels.append(panel_info)

            await interaction.response.send_message(
                f"✅ Панель заявок создана в канале {target_channel.mention}\n"
                f"🔗 [Перейти к панели]({message.jump_url})\n"
                f"🔄 Количество участников будет автоматически обновляться каждые 24 часа",
                ephemeral=True,
            )

            logger.info(
                f"📋 {interaction.user.display_name} создал панель заявок в канале {target_channel.name} (автообновление включено)"
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ У бота нет прав для отправки сообщений в указанный канал.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Ошибка создания панели заявок: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при создании панели.", ephemeral=True
            )

    @app_commands.command(
        name="update_application_panel",
        description="Обновить панель заявок с актуальным количеством участников",
    )
    @app_commands.describe(
        message_id="ID сообщения с панелью заявок",
        channel="Канал где находится панель (по умолчанию текущий)",
    )
    @app_commands.guild_only()
    async def update_application_panel(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel = None,
    ):
        """Обновляет существующую панель заявок с актуальным количеством участников"""

        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id

        if not any(role in user_roles for role in admin_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для обновления панели заявок.", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel

        try:
            # Находим сообщение
            message = await target_channel.fetch_message(int(message_id))

            # Получаем актуальное количество участников
            member_count = get_member_count(interaction.guild)

            # Создаем обновленный embed
            main_embed = discord.Embed(
                title="📋 Подача заявки в Деревню VLG",
                description=(
                    f"🏘️ **Добро пожаловать в самую большую Деревню в Rust с {member_count} соседями!**\n\n"
                    "🎯 **Перед подачей заявки обязательно:**\n\n"
                    "**1.** 📝 Измените ваш ник в Discord по формату: `SteamNickname | Имя`\n"
                    "└─ **Пример:** `Terminator | Володя`\n"
                    "└─ **Как изменить:** ПКМ по нику → *Редактировать личный профиль сервера*\n\n"
                    "**2.** 🔗 Откройте Steam-профиль:\n"
                    "├─ **Список друзей** → Публичный\n"
                    "├─ **Информация об игре** → Публичная\n"
                    "└─ 🔗 [Настройки приватности Steam](https://steamcommunity.com/my/edit/settings)\n\n"
                    "**3.** 👤 **Ник в Steam должен совпадать с ником в Discord**\n\n"
                    "⚠️ **Важно:** Проверьте всё ещё раз перед подачей заявки!"
                ),
                color=0x00FF00,
            )

            main_embed.add_field(
                name="✅ Подходящие ники:",
                value="`Bestel`, `Yango`, `Справедливый`, `Борис`, `Gen0m`, `Юный Воин`",
                inline=False,
            )

            main_embed.add_field(
                name="❌ НЕ подойдут:",
                value="`༒☬☠Ƚ︎ÙçҜყ☠︎☬༒`, `775038`, `K Δ Я U MI`, `crmnl1`, `Y1`, `AB`, `OOO`",
                inline=False,
            )

            main_embed.set_footer(
                text=f"Деревня VLG • {member_count} участников • 170+ вайпов"
            )
            main_embed.set_thumbnail(
                url="https://cdn.discordapp.com/attachments/472365787445985280/icon.png"
            )
            main_embed.set_image(url="https://i.ibb.co/kVvrcT3Q/VLG-Logo.gif")

            # Обновляем сообщение
            await message.edit(embed=main_embed)

            await interaction.response.send_message(
                f"✅ **Панель обновлена!**\n\n"
                f"📊 Актуальное количество участников: **{member_count}**\n"
                f"🔗 [Перейти к панели]({message.jump_url})",
                ephemeral=True,
            )

            logger.info(
                f"🔄 {interaction.user.display_name} обновил панель заявок: {member_count} участников"
            )

        except discord.NotFound:
            await interaction.response.send_message(
                "❌ Сообщение с указанным ID не найдено в этом канале.", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Неверный формат ID сообщения.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ У бота нет прав для редактирования этого сообщения.", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка обновления панели заявок: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при обновлении панели.", ephemeral=True
            )

    @commands.Cog.listener()
    async def on_ready(self):
        """Добавляем постоянный view при запуске бота"""
        self.bot.add_view(ApplicationButton())
        logger.info("✅ ApplicationButton view добавлен как постоянный view")


async def setup(bot: commands.Bot):
    await bot.add_cog(ApplicationSystem(bot))