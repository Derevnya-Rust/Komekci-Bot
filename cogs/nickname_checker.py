import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import re
from typing import List, Dict, Set
import difflib
from utils.validators import is_valid_nickname, parse_discord_nick, hard_check_full
from utils.nickname_filter import filter_nickname
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class NicknameChecker(commands.Cog):
    """Проверка никнеймов участников сервера"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # ID ролей для проверки
        self.CHECK_ROLES = {
            1257813489595191296,  # Новичок
            1208155640355229757,  # Гость
            945469407944118362,  # Житель
            1176935405195636856,  # Гражданин
        }

    def check_nickname_similarity(
        self, nickname1: str, nickname2: str, threshold: float = 0.8
    ) -> bool:
        """Проверяет схожесть двух никнеймов"""
        clean1 = parse_discord_nick(nickname1)
        clean2 = parse_discord_nick(nickname2)

        if not clean1 or not clean2:
            return False

        # Точное совпадение
        if clean1 == clean2:
            return True

        # Проверка схожести
        similarity = difflib.SequenceMatcher(None, clean1, clean2).ratio()
        return similarity >= threshold

    def check_duplicate_nicknames(
        self, members: List[discord.Member]
    ) -> Dict[str, List[discord.Member]]:
        """Находит дублирующиеся или похожие никнеймы"""
        duplicates = {}
        checked_pairs = set()
        total_comparisons = len(members) * (len(members) - 1) // 2

        logger.info(f"🔍 Начинаю сравнение {total_comparisons} пар никнеймов")

        for i, member1 in enumerate(members):
            # Логируем прогресс каждые 100 участников
            if i % 100 == 0 and i > 0:
                logger.info(f"🔄 Обработано {i}/{len(members)} участников")

            for j, member2 in enumerate(members[i + 1 :], i + 1):
                pair_id = tuple(sorted([member1.id, member2.id]))
                if pair_id in checked_pairs:
                    continue
                checked_pairs.add(pair_id)

                if self.check_nickname_similarity(
                    member1.display_name, member2.display_name
                ):
                    clean_name = parse_discord_nick(member1.display_name)
                    if clean_name not in duplicates:
                        duplicates[clean_name] = []

                    # Добавляем участников только если их еще нет в одной группе
                    if member1 not in duplicates[clean_name]:
                        duplicates[clean_name].append(member1)
                    if member2 not in duplicates[clean_name]:
                        duplicates[clean_name].append(member2)

        return duplicates

    def check_inappropriate_nicknames(
        self, members: List[discord.Member]
    ) -> List[tuple]:
        """Проверяет никнеймы на соответствие правилам"""
        inappropriate = []

        for member in members:
            # Проверка фильтром неподобающих слов
            is_blocked, reason, user_message = filter_nickname(member.display_name)
            if is_blocked:
                inappropriate.append((member, f"🚫 Неподобающее содержимое: {reason}"))
                continue

            # КРИТИЧЕСКАЯ ПРОВЕРКА: формат разделителя (ПРИОРИТЕТНАЯ)
            if "|" in member.display_name and " | " not in member.display_name:
                inappropriate.append((member, f"🚫 КРИТИЧЕСКАЯ ОШИБКА: Неправильный формат разделителя! Должно быть 'SteamNick | Имя' (с пробелами)"))
                continue
                
            # КРИТИЧЕСКАЯ ПРОВЕРКА: латинские имена (ПРИОРИТЕТНАЯ)
            if " | " in member.display_name:
                parts = member.display_name.split(" | ")
                if len(parts) == 2:
                    game_nick, real_name = parts
                    # Строгая проверка: если есть хотя бы одна латинская буква - блокируем
                    if re.search(r"[a-zA-Z]", real_name):
                        inappropriate.append((member, f"🚫 КРИТИЧЕСКАЯ ОШИБКА: Имя '{real_name}' содержит латинские буквы! Должно быть ТОЛЬКО кириллицей"))
                        continue

            # Проверка валидатором
            is_valid, error_message, _ = is_valid_nickname(
                member.display_name
            )
            if not is_valid:
                inappropriate.append((member, f"❌ {error_message}"))

        return inappropriate

    @app_commands.command(
        name="nicknames", description="Проверяет никнеймы участников сервера"
    )
    @app_commands.guild_only()
    async def check_nicknames(self, interaction: discord.Interaction):
        """Проверяет никнеймы участников сервера"""
        try:
            await interaction.response.defer()

            # Получаем участников с нужными ролями
            members_to_check = []
            for member in interaction.guild.members:
                if any(role.id in self.CHECK_ROLES for role in member.roles):
                    members_to_check.append(member)

            # Проверяем дубликаты и неподобающие никнеймы
            duplicates = self.check_duplicate_nicknames(members_to_check)
            inappropriate = self.check_inappropriate_nicknames(members_to_check)

            # Формируем отчет
            embed = discord.Embed(
                title="📊 Отчет по никнеймам",
                color=0x3498DB,
                timestamp=datetime.now(timezone.utc),
            )

            if duplicates:
                duplicate_text = []
                for clean_name, members in duplicates.items():
                    member_list = ", ".join([f"{m.display_name}" for m in members])
                    duplicate_text.append(f"**{clean_name}**: {member_list}")

                embed.add_field(
                    name=f"🔄 Дубликаты никнеймов ({len(duplicates)})",
                    value="\n".join(duplicate_text)[:1024],
                    inline=False,
                )

            if inappropriate:
                inappropriate_text = []
                for member, reason in inappropriate:
                    inappropriate_text.append(f"**{member.display_name}**: {reason}")

                embed.add_field(
                    name=f"❌ Проблемные никнеймы ({len(inappropriate)})",
                    value="\n".join(inappropriate_text)[:1024],
                    inline=False,
                )

            if not duplicates and not inappropriate:
                embed.add_field(
                    name="✅ Результат",
                    value="Все никнеймы соответствуют требованиям",
                    inline=False,
                )

            embed.set_footer(text=f"Проверено участников: {len(members_to_check)}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка проверки никнеймов: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при проверке никнеймов.", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(NicknameChecker(bot))
