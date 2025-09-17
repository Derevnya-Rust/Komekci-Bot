import discord
from discord.ext import commands
from discord import app_commands
from utils.kb import update_from_channels, load_kb


class KBSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="sync_kb", description="Обновить базу знаний из каналов Деревни"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sync_kb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        stats = await update_from_channels(self.bot)
        # Принудительно перезагружаем базу знаний включая FAQ
        final_stats = load_kb()
        await interaction.followup.send(
            f"Готово. Сообщений: {stats.get('messages',0)}. Фрагментов: {final_stats.get('chunks',0)}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(KBSync(bot))
