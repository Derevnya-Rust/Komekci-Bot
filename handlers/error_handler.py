
import discord
import logging
import asyncio
from typing import Optional, List
from utils.logger import get_module_logger

logger = get_module_logger(__name__)

class ErrorMessageView(discord.ui.View):
    def __init__(self, user_id: int, steam_url: str = ""):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.steam_url = steam_url

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяем, что кнопки может нажимать автор заявки или модераторы"""
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин", "Администратор"]
        is_author = interaction.user.id == self.user_id
        is_admin = any(role in user_roles for role in admin_roles)

        if not (is_author or is_admin):
            await interaction.response.send_message(
                "❌ Только автор заявки или модераторы могут использовать эти кнопки.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🔄 Перепроверить заявку", style=discord.ButtonStyle.success, emoji="🔄", custom_id="error_recheck_application")
    async def recheck_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Перепроверка заявки после ошибки"""
        try:
            # Определяем автора заявки
            author = interaction.guild.get_member(self.user_id)
            if not author:
                await interaction.response.send_message(
                    "❌ Автор заявки не найден на сервере.",
                    ephemeral=True
                )
                return

            await interaction.response.defer()

            # Очищаем кэш Steam для свежей проверки
            try:
                from handlers.steam_api import steam_client
                from handlers.novichok import extract_steam_id_from_url

                if self.steam_url:
                    steam_id = extract_steam_id_from_url(self.steam_url)
                    if steam_id:
                        steam_client.force_cache_clear_for_profile(steam_id)
                        logger.info(f"🗑️ Очищен кэш Steam для перепроверки")
            except Exception as e:
                logger.error(f"Ошибка очистки кэша Steam: {e}")

            # Запускаем перепроверку
            from handlers.tickets import TicketHandler
            bot = interaction.client
            ticket_handler = bot.get_cog('TicketHandler')

            if ticket_handler:
                await ticket_handler.analyze_and_respond_to_application(interaction.channel, author)
                await interaction.edit_original_response(content="✅ Перепроверка заявки запущена!")
            else:
                await interaction.edit_original_response(content="❌ Система проверки заявок временно недоступна.")

        except Exception as e:
            logger.error(f"❌ Ошибка перепроверки заявки: {e}")
            await interaction.edit_original_response(content="❌ Произошла ошибка при перепроверке.")

    @discord.ui.button(label="🔧 Исправить автоматически", style=discord.ButtonStyle.secondary, emoji="🔧", custom_id="error_auto_fix")
    async def auto_fix_errors(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Автоматическое исправление ошибок"""
        try:
            # Определяем автора заявки
            author = interaction.guild.get_member(self.user_id)
            if not author:
                await interaction.response.send_message(
                    "❌ Автор заявки не найден на сервере.",
                    ephemeral=True
                )
                return

            await interaction.response.defer()

            # Пытаемся исправить никнейм автоматически
            from utils.validators import auto_fix_nickname
            
            original_nickname = author.display_name
            fixed_nickname, fixes_applied = auto_fix_nickname(original_nickname)

            if fixed_nickname != original_nickname and fixes_applied:
                # Предлагаем исправления
                from handlers.novichok_actions import AutoFixConfirmationView
                fix_view = AutoFixConfirmationView(
                    author.id, 
                    original_nickname, 
                    fixed_nickname, 
                    fixes_applied
                )

                embed = discord.Embed(
                    title="🔧 Предложение автоматического исправления",
                    description=f"Обнаружены исправимые ошибки в никнейме:",
                    color=0x3498db
                )
                embed.add_field(
                    name="📝 Текущий никнейм",
                    value=f"`{original_nickname}`",
                    inline=False
                )
                embed.add_field(
                    name="✨ Исправленный никнейм", 
                    value=f"`{fixed_nickname}`",
                    inline=False
                )
                embed.add_field(
                    name="🔧 Применённые исправления",
                    value="\n".join([f"• {fix}" for fix in fixes_applied]),
                    inline=False
                )

                await interaction.edit_original_response(embed=embed, view=fix_view)
            else:
                await interaction.edit_original_response(content="✅ Автоматические исправления не требуются или невозможны.")

        except Exception as e:
            logger.error(f"❌ Ошибка автоисправления: {e}")
            await interaction.edit_original_response(content="❌ Произошла ошибка при автоисправлении.")utton):
        """Кнопка перепроверки заявки"""
        try:
            await interaction.response.send_message("🔄 Запускаю перепроверку заявки...", ephemeral=True)

            # Получаем автора заявки
            author = interaction.guild.get_member(self.user_id)
            if not author:
                await interaction.edit_original_response(content="❌ Автор заявки не найден на сервере.")
                return

            # Получаем TicketHandler для перепроверки
            ticket_handler = interaction.client.get_cog('TicketHandler')
            if ticket_handler:
                # Очищаем кэш Steam для свежей проверки
                try:
                    from handlers.tickets import clear_steam_cache
                    clear_steam_cache(interaction.channel.id, author.id)
                    logger.info(f"🗑️ Очищен кэш Steam для перепроверки после ошибки {author.display_name}")
                except Exception as e:
                    logger.error(f"Ошибка очистки кэша: {e}")

                # Запускаем анализ заявки с задержкой
                await asyncio.sleep(2)
                await ticket_handler.analyze_and_respond_to_application(interaction.channel, author)

                await interaction.edit_original_response(content="✅ Перепроверка заявки запущена!")
                logger.info(f"✅ Перепроверка после ошибки запущена для {author.display_name}")
            else:
                await interaction.edit_original_response(content="❌ Система обработки заявок недоступна. Обратитесь к администратору.")

        except Exception as e:
            logger.error(f"❌ Ошибка перепроверки после ошибки: {e}")
            try:
                await interaction.edit_original_response(content="❌ Произошла ошибка при перепроверке заявки.")
            except:
                pass

    @discord.ui.button(label="🏠 Позвать Деревню на помощь", style=discord.ButtonStyle.secondary, emoji="🏠", custom_id="error_call_for_help")
    async def call_for_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Кнопка призыва помощи от Деревни"""
        try:
            await interaction.response.send_message("🏠 Призываю помощь от Деревни...", ephemeral=True)

            # Получаем автора заявки
            author = interaction.guild.get_member(self.user_id)
            if not author:
                await interaction.edit_original_response(content="❌ Автор заявки не найден на сервере.")
                return

            # Отправляем сообщение с призывом о помощи
            help_message = f"""🆘 **{author.mention} просит помощи с заявкой!**

💡 **Жители Деревни, помогите разобраться:**
• Проверьте никнейм в формате `SteamNickname | Имя`
• Убедитесь что Steam-профиль открыт
• Подскажите что нужно исправить

🔗 **Полезные ссылки:**
• [Настройки приватности Steam](https://steamcommunity.com/my/edit/settings)
• Канал помощи: <#1178436876244361388>

⚠️ **Не создавайте новую заявку!** Исправьте проблемы в этом канале."""

            await safe_send_message(interaction.channel, help_message)

            await interaction.edit_original_response(content="✅ Деревня призвана на помощь! Ожидайте ответа от жителей.")
            logger.info(f"🆘 Призвана помощь от Деревни для {author.display_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка призыва помощи: {e}")
            try:
                await interaction.edit_original_response(content="❌ Произошла ошибка при призыве помощи.")
            except:
                pass

    @discord.ui.button(label="🆘 Позвать Деревню на помощь", style=discord.ButtonStyle.secondary, emoji="🆘")
    async def call_for_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Кнопка вызова помощи от жителей"""
        try:
            await interaction.response.defer()

            # Получаем автора заявки
            author = interaction.guild.get_member(self.user_id)
            if not author:
                await interaction.followup.send("❌ Автор заявки не найден на сервере.", ephemeral=True)
                return

            # Добавляем роль @гость автору заявки
            guest_role = interaction.guild.get_role(1208155640355229757)  # ID роли @гость
            if guest_role and guest_role not in author.roles:
                await author.add_roles(guest_role, reason="Запрошена помощь с заявкой")
                logger.info(f"✅ Добавлена роль @гость пользователю {author.display_name}")

            # Отправляем сообщение с пингом ролей
            help_message = f"🆘 **Просьба помочь {author.mention} с заявкой!**\n\n" \
                          f"<@&1208155640355229757> <@&1208155641013821460> <@&1208155641013821461>\n\n" \
                          f"💬 Пользователь испытывает трудности с оформлением заявки и нуждается в поддержке жителей Деревни."

            await interaction.channel.send(help_message)

            await interaction.followup.send(
                "✅ Помощь вызвана! Жители Деревни скоро помогут вам с заявкой.",
                ephemeral=True
            )

            logger.info(f"🆘 Вызвана помощь для {author.display_name} пользователем {interaction.user.display_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка вызова помощи: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при вызове помощи.",
                ephemeral=True
            )


def create_user_friendly_error_message(
    error_type: str,
    user_mention: str,
    user_id: int,
    steam_url: str = "",
    custom_message: str = None
) -> tuple[discord.Embed, ErrorMessageView]:
    """
    Создает понятное пользователю сообщение об ошибке с кнопками помощи
    
    Args:
        error_type: тип ошибки ('steam_error', 'nickname_error', 'technical_error', etc.)
        user_mention: упоминание пользователя
        user_id: ID пользователя
        steam_url: Steam URL (если есть)
        custom_message: кастомное сообщение об ошибке
    
    Returns:
        tuple с Embed и View для отправки
    """
    
    # Базовые сообщения для разных типов ошибок
    error_messages = {
        'steam_error': {
            'title': '⚠️ Проблема с проверкой Steam профиля',
            'description': f'{user_mention}, возникла временная проблема при проверке вашего Steam профиля.',
            'solution': '🔧 **Что можно сделать:**\n' \
                       '• Убедитесь что ваш Steam профиль открыт\n' \
                       '• Проверьте настройки приватности Steam\n' \
                       '• Попробуйте перепроверить заявку через несколько минут'
        },
        'nickname_error': {
            'title': '📝 Проблема с никнеймом',
            'description': f'{user_mention}, обнаружена проблема с форматом вашего никнейма.',
            'solution': '🔧 **Как исправить:**\n' \
                       '• Измените ник на формат: `SteamNickname | Имя`\n' \
                       '• Убедитесь что есть пробелы до и после символа |\n' \
                       '• Ник должен быть приличным и понятным'
        },
        'technical_error': {
            'title': '🔧 Техническая проблема',
            'description': f'{user_mention}, произошла временная техническая проблема при обработке вашей заявки.',
            'solution': '🔧 **Что делать:**\n' \
                       '• Попробуйте перепроверить заявку через 1-2 минуты\n' \
                       '• Если проблема повторяется - вызовите помощь жителей\n' \
                       '• Наши модераторы решат проблему вручную'
        },
        'undefined_error': {
            'title': '❓ Неопределенная проблема',
            'description': f'{user_mention}, не удалось определить проблему с вашей заявкой.',
            'solution': '🔧 **Рекомендации:**\n' \
                       '• Проверьте все требования к заявке\n' \
                       '• Попробуйте перепроверить заявку\n' \
                       '• Обратитесь за помощью к жителям Деревни'
        }
    }
    
    # Получаем сообщение для типа ошибки или используем дефолтное
    error_info = error_messages.get(error_type, error_messages['undefined_error'])
    
    # Создаем embed
    embed = discord.Embed(
        title=error_info['title'],
        description=error_info['description'],
        color=0xff9900  # Оранжевый цвет для предупреждений
    )
    
    # Добавляем кастомное сообщение если есть
    if custom_message:
        embed.add_field(
            name="📋 Детали проблемы",
            value=custom_message,
            inline=False
        )
    
    # Добавляем решение
    embed.add_field(
        name="💡 Решение",
        value=error_info['solution'],
        inline=False
    )
    
    # Добавляем информационное поле
    embed.add_field(
        name="ℹ️ Важно",
        value="Не создавайте новую заявку! Используйте кнопки ниже для решения проблемы.",
        inline=False
    )
    
    embed.set_footer(text="Деревня VLG • Система поддержки заявок")
    
    # Создаем view с кнопками
    view = ErrorMessageView(user_id, steam_url)
    
    return embed, view


def handle_steam_nick_error(error_message: str) -> str:
    """Обрабатывает ошибку 'steam_nick_clean' и возвращает понятное сообщение"""
    if "steam_nick_clean" in error_message.lower():
        return "technical_error"
    elif "not defined" in error_message.lower():
        return "technical_error"
    elif "timeout" in error_message.lower():
        return "steam_error"
    else:
        return "undefined_error"


async def send_user_friendly_error(
    channel: discord.TextChannel,
    error_type: str,
    user: discord.Member,
    steam_url: str = "",
    custom_message: str = None,
    original_error: str = None
) -> Optional[discord.Message]:
    """
    Отправляет понятное пользователю сообщение об ошибке
    
    Args:
        channel: канал для отправки
        error_type: тип ошибки
        user: пользователь
        steam_url: Steam URL
        custom_message: кастомное сообщение
        original_error: оригинальная ошибка (только для логов)
    
    Returns:
        Отправленное сообщение или None
    """
    try:
        # Логируем техническую ошибку
        if original_error:
            logger.error(f"❌ Техническая ошибка для {user.display_name}: {original_error}")

        # Создаем понятное сообщение
        embed, view = create_user_friendly_error_message(
            error_type, 
            user.mention, 
            user.id, 
            steam_url, 
            custom_message
        )
        
        # Отправляем сообщение
        from utils.rate_limiter import safe_send_message
        message = await safe_send_message(channel, embed=embed, view=view)
        
        if message:
            logger.info(f"✅ Отправлено понятное сообщение об ошибке типа '{error_type}' для {user.display_name}")
        
        return message
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки понятного сообщения об ошибке: {e}")
        
        # Fallback - отправляем базовое сообщение
        try:
            fallback_message = f"⚠️ {user.mention} Возникла проблема с обработкой вашей заявки. " \
                             f"Пожалуйста, обратитесь к жителям Деревни за помощью."
            await channel.send(fallback_message)
        except:
            pass
        
        return None
