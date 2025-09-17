import discord
from discord.ext import commands
from discord import app_commands
import logging
from utils.rate_limiter import safe_send_message, safe_send_followup

logger = logging.getLogger(__name__)


class EntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🚪 Вступить в Деревню",
        style=discord.ButtonStyle.success,
        custom_id="entry_button",
        emoji="🏘️",
    )
    async def entry_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Кнопка для вступления в Деревню"""
        user = interaction.user

        # Проверяем, есть ли уже роль у пользователя
        user_roles = [role.name for role in user.roles]
        if any(
            role in user_roles for role in ["Новичок", "Гость", "Житель", "Гражданин"]
        ):
            await interaction.response.send_message(
                "✅ Вы уже являетесь участником Деревни VLG!", ephemeral=True
            )
            return

        # Создаем embed с информацией о вступлении
        embed = discord.Embed(
            title="🏘️ Добро пожаловать в Деревню VLG!",
            description=(
                "Спасибо за интерес к нашему сообществу! Для вступления необходимо:\n\n"
                "**1.** Переименуйте ваш ник в Discord по формату: `SteamNickname | Имя`\n"
                "**2.** Откройте ваш Steam-профиль (друзья и игры должны быть видны)\n"
                "**3.** Создайте тикет в канале поддержки для подачи заявки\n\n"
                "📝 **В анкете укажите:**\n• Steam-профиль (обязательно)\n\n"
                "💡 **Подсказка:** Используйте команду `/ticket` или найдите канал с созданием тикетов"
            ),
            color=0x00FF00,
        )
        embed.add_field(
            name="📋 Требования к нику",
            value="• Читаемый и адекватный\n• Без мата и оскорблений\n• Без символов типа ♛☬卍",
            inline=True,
        )
        embed.add_field(
            name="🎮 Steam профиль",
            value="• Список друзей открыт\n• Время в играх видно\n• Профиль публичный",
            inline=True,
        )
        embed.add_field(
            name="⏰ Процесс рассмотрения",
            value="• Заявки рассматриваются в течение суток\n• Модераторы проверят ваш профиль\n• Результат сообщат в тикете",
            inline=False,
        )
        embed.set_footer(text="Деревня VLG • 3800+ участников • 170+ вайпов")
        embed.set_thumbnail(
            url="https://cdn.discordapp.com/icons/472365787445985280/a_1234567890abcdef.gif"
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

        logger.info(
            f"👋 Пользователь {user.display_name} ({user.id}) нажал кнопку вступления в Деревню"
        )


class ApplicationModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Заявка на вступление в Деревню VLG")

        # Основное поле (обязательное)
        self.steam_url = discord.ui.TextInput(
            label="Ссылка На Ваш Steam-Профиль",
            placeholder="https://steamcommunity.com/profiles/YOUR_ID",
            required=True,
            max_length=200,
        )

        # Дополнительное поле (необязательное)
        self.questions = discord.ui.TextInput(
            label="Есть ли какие-то вопросы про Деревню нашу?",
            placeholder="Напишите ваши вопросы или оставьте пустым (необязательно)",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )

        # Добавляем поля в модальное окно
        self.add_item(self.steam_url)
        self.add_item(self.questions)

    async def on_submit(self, interaction: discord.Interaction):
        """Обработка отправки заявки"""
        try:
            # Создаем embed для заявки
            embed = discord.Embed(
                title="📋 Новая заявка на вступление",
                color=0x00FF00,
                timestamp=discord.utils.utcnow(),
            )

            # Основная информация
            embed.add_field(
                name="🔗 Steam профиль",
                value=self.steam_url.value.strip(),
                inline=False,
            )

            # Дополнительные вопросы (если указаны)
            if self.questions.value.strip():
                embed.add_field(
                    name="❓ Вопросы про Деревню",
                    value=self.questions.value.strip(),
                    inline=False,
                )

            # Информация о пользователе
            embed.add_field(
                name="👤 Подал заявку",
                value=f"{interaction.user.mention} ({interaction.user.name})",
                inline=True,
            )

            embed.add_field(
                name="🆔 Discord ID", value=f"`{interaction.user.id}`", inline=True
            )

            embed.set_footer(text=f"Заявка подана {interaction.user.name}")

            # Отправляем в тикет канал
            ticket_channel = await self.create_ticket_channel(
                interaction.guild, interaction.user
            )

            await ticket_channel.send(embed=embed)

            # Ответ пользователю
            await interaction.response.send_message(
                f"✅ **Заявка успешно подана!**\n\n"
                f"Ваш тикет создан: {ticket_channel.mention}\n"
                f"Наши модераторы рассмотрят вашу заявку в ближайшее время.",
                ephemeral=True,
            )

            logger.info(
                f"✅ Заявка подана: {interaction.user.name} → {ticket_channel.name}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка при обработке заявки: {e}")
            await interaction.response.send_message(
                "❌ Произошла ошибка при подаче заявки. Попробуйте позже.",
                ephemeral=True,
            )

    async def create_ticket_channel(
        self, guild: discord.Guild, user: discord.User
    ) -> discord.TextChannel:
        """Создает тикет канал для пользователя"""
        # Находим или создаем категорию для тикетов
        category = discord.utils.get(guild.categories, name="Тикеты")
        if not category:
            category = await guild.create_category("Тикеты")

        # Создаем канал с именем пользователя
        channel_name = f"new_{user.name}"
        channel = await category.create_text_channel(channel_name)

        # Выдаем права пользователю на просмотр канала
        await channel.set_permissions(user, read_messages=True, send_messages=True)

        return channel


class EntryForm(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ticket", description="Создать заявку на вступление в Деревню"
    )
    async def ticket_command(self, interaction: discord.Interaction):
        """Обработчик команды /ticket"""
        await interaction.response.send_modal(ApplicationModal())

    @app_commands.command(
        name="help_commands", description="Показать полный список доступных команд бота"
    )
    async def help_commands(self, interaction: discord.Interaction):
        """Показать список команд бота"""
        # Перенаправляем на основную команду /help
        await interaction.response.send_message(
            "ℹ️ **Используйте команду `/help` для получения полного справочника!**\n\n"
            "Команда `/help` содержит все доступные команды с подробными описаниями, "
            "отсортированные по категориям и с учетом ваших прав доступа.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_ready(self):
        """Добавляем постоянный view при запуске бота"""
        self.bot.add_view(EntryView())
        logger.info("✅ EntryView добавлен как постоянный view")


async def setup(bot: commands.Bot):
    await bot.add_cog(EntryForm(bot))
