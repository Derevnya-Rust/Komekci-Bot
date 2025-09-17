import discord
from discord.ext import commands
from discord import app_commands
from utils.nickname_filter import filter_nickname
from datetime import datetime, timezone
import json
import logging
from typing import List
import asyncio

logger = logging.getLogger(__name__)


class NicknameAdmin(commands.Cog):
    """Администрирование фильтра никнеймов"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="test_nickname_filter", description="Протестировать фильтр никнеймов"
    )
    @app_commands.describe(nickname="Никнейм для тестирования")
    @app_commands.guild_only()
    async def test_nickname_filter(
        self, interaction: discord.Interaction, nickname: str
    ):
        """Тестирует фильтр никнеймов на конкретном примере"""

        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин", "Администратор"]

        if not any(role in user_roles for role in admin_roles):
            await interaction.response.send_message(
                "❌ У вас нет прав для тестирования фильтра.", ephemeral=True
            )
            return

        try:
            from utils.nickname_filter import filter_nickname

            is_blocked, reason, user_message = filter_nickname(nickname)

            if is_blocked:
                embed = discord.Embed(
                    title="🚫 Никнейм заблокирован",
                    description=f"**Тестируемый никнейм:** `{nickname}`",
                    color=0xFF0000,
                )
                embed.add_field(
                    name="🔍 Причина блокировки:", value=reason, inline=False
                )
                embed.add_field(
                    name="💬 Сообщение пользователю:",
                    value=(
                        user_message[:1000] + "..."
                        if len(user_message) > 1000
                        else user_message
                    ),
                    inline=False,
                )
            else:
                embed = discord.Embed(
                    title="✅ Никнейм прошел проверку",
                    description=f"**Тестируемый никнейм:** `{nickname}`",
                    color=0x00FF00,
                )
                embed.add_field(
                    name="📊 Результат:",
                    value="Никнейм не содержит неподобающего контента",
                    inline=False,
                )

            embed.set_footer(text=f"Тест выполнен {interaction.user.display_name}")

            await interaction.response.send_message(embed=embed, ephemeral=True)

            logger.info(
                f"🧪 {interaction.user.display_name} протестировал никнейм '{nickname}': блокирован={is_blocked}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка тестирования фильтра: {e}")
            await interaction.response.send_message(
                f"❌ Ошибка при тестировании фильтра: {str(e)}", ephemeral=True
            )

    @app_commands.command(
        name="nickname_filter_stats", description="Статистика работы фильтра никнеймов"
    )
    @app_commands.guild_only()
    async def nickname_filter_stats(self, interaction: discord.Interaction):
        """Показывает статистику фильтра никнеймов"""

        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин", "Администратор"]

        if not any(role in user_roles for role in admin_roles):
            await interaction.response.send_message(
                "❌ У вас нет прав для просмотра статистики фильтра никнеймов.",
                ephemeral=True,
            )

    @app_commands.command(
        name="moderate_nickname", description="Проверить никнейм по правилам модерации"
    )
    @app_commands.describe(nickname="Никнейм в формате 'ИгровойНик | Имя'")
    @app_commands.guild_only()
    async def moderate_nickname_command(
        self, interaction: discord.Interaction, nickname: str
    ):
        """Проверяет никнейм по строгим правилам модерации"""

        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин", "Администратор"]

        if not any(role in user_roles for role in admin_roles):
            await interaction.response.send_message(
                "❌ У вас нет прав для использования модератора никнеймов.",
                ephemeral=True,
            )
            return

        try:
            # Локальный импорт для избежания циклических зависимостей
            from utils.nickname_moderator import NicknameModerator
            
            # Используем модератор никнеймов
            moderator = NicknameModerator()
            result = await moderator.check_nickname(interaction.user, nickname)
            moderator = NicknameModerator()
            result = await moderator.check_nickname(nickname)

            # Создаем embed с результатом
            if result.approve:
                embed = discord.Embed(
                    title="✅ Никнейм одобрен",
                    description=f"**Проверенный никнейм:** `{nickname}`",
                    color=0x00FF00,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(
                    name="📝 Статус",
                    value="Соответствует всем требованиям",
                    inline=False,
                )
            else:
                embed = discord.Embed(
                    title="❌ Никнейм отклонен",
                    description=f"**Проверенный никнейм:** `{nickname}`",
                    color=0xFF0000,
                    timestamp=datetime.now(timezone.utc),
                )

                if result.reasons:
                    embed.add_field(
                        name="🚫 Причины отклонения",
                        value="\n".join(f"• {reason}" for reason in result.reasons),
                        inline=Falsese,
                    )

                if result["fixed_full"]:
                    embed.add_field(
                        name="🔧 Предлагаемое исправление",
                        value=f"`{result['fixed_full']}`",
                        inline=False,
                    )

            if result["notes_to_user"]:
                embed.add_field(
                    name="💡 Рекомендации",
                    value=result["notes_to_user"],
                    inline=False,
                )

            embed.set_footer(text=f"Проверку выполнил {interaction.user.display_name}")

            await interaction.response.send_message(embed=embed, ephemeral=True)

            logger.info(
                f"🧪 {interaction.user.display_name} проверил никнейм '{nickname}': одобрен={result['approve']}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка модерации никнейма: {e}")
            await interaction.response.send_message(
                f"❌ Ошибка при проверке никнейма: {str(e)}", ephemeral=True
            )

    @app_commands.command(
        name="add_banned_word", description="Добавить слово в черный список фильтра"
    )
    @app_commands.describe(word="Слово для добавления в черный список")
    @app_commands.guild_only()
    async def add_banned_word(self, interaction: discord.Interaction, word: str):
        """Добавляет слово в черный список фильтра"""

        # Проверяем права (только высшие администраторы)
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Гражданин", "Администратор"]

        if not any(role in user_roles for role in admin_roles):
            await interaction.response.send_message(
                "❌ У вас нет прав для управления черным списком.", ephemeral=True
            )
            return

        try:
            from utils.nickname_filter import nickname_filter

            word_clean = word.strip().lower()

            if not word_clean:
                await interaction.response.send_message(
                    "❌ Слово не может быть пустым.", ephemeral=True
                )
                return

            if word_clean in nickname_filter.banned_words_full:
                await interaction.response.send_message(
                    f"⚠️ Слово '{word_clean}' уже есть в черном списке.", ephemeral=True
                )
                return

            # Добавляем слово
            nickname_filter.banned_words_full.append(word_clean)

            embed = discord.Embed(
                title="✅ Слово добавлено в черный список",
                description=f"**Добавленное слово:** `{word_clean}`",
                color=0x00FF00,
            )

            embed.add_field(
                name="📊 Статистика:",
                value=f"Всего слов в черном списке: {len(nickname_filter.banned_words_full)}",
                inline=False,
            )

            embed.set_footer(
                text=f"Добавлено администратором {interaction.user.display_name}"
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

            logger.info(
                f"📝 {interaction.user.display_name} добавил слово '{word_clean}' в черный список фильтра"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка добавления слова: {e}")
            await interaction.response.send_message(
                f"❌ Ошибка при добавлении слова: {str(e)}", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(NicknameAdmin(bot))