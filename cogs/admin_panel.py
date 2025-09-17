import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import os
import json
from datetime import datetime, timezone
from config import config

logger = logging.getLogger(__name__)


def load_bot_settings():
    """Загружает настройки бота из файла"""
    try:
        with open("bot_settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # Создаем файл с настройками по умолчанию
        default_settings = {
            "ticket_system": {"channel_prefix": "new_", "auto_responses": True},
            "channels": {
                "notification_channel": config.NOTIFICATION_CHANNEL_ID,
                "log_channel": config.LOG_CHANNEL_ID,
                "mod_channel": config.MOD_CHANNEL_ID,
                "debug_channel": config.DEBUG_CHANNEL_ID,
            },
            "security": {"min_account_age_days": config.MIN_ACCOUNT_AGE_DAYS},
            "general": {
                "custom_member_count": "",
                "bot_status_text": "за Деревней VLG",
            },
            "ai": {"custom_system_prompt": ""},
            "messages": {"welcome_template": "Добро пожаловать в Деревню VLG!"},
            "application_form": {
                "fields": {
                    "steam_profile": {
                        "label": "🔗 Ссылка на ваш Steam-профиль",
                        "placeholder": "https://steamcommunity.com/profiles/YOUR_ID",
                        "required": True,
                        "max_length": 200,
                    },
                    "questions": {
                        "label": "❓ Есть ли какие-то вопросы про Деревню нашу?",
                        "placeholder": "Напишите ваши вопросы или оставьте пустым (необязательно)",
                        "required": False,
                        "max_length": 500,
                    },
                }
            },
        }
        save_bot_settings(default_settings)
        return default_settings


def save_bot_settings(settings):
    """Сохраняет настройки бота в файл"""
    try:
        with open("bot_settings.json", "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        logger.info("✅ Настройки бота сохранены")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения настроек: {e}")
        raise


class AdminSettingsModal(discord.ui.Modal):
    def __init__(self, setting_type: str, current_value: str = ""):
        super().__init__(title=f"Настройка: {setting_type}")
        self.setting_type = setting_type

        self.value_input = discord.ui.TextInput(
            label="Новое значение",
            placeholder=f"Текущее: {current_value}",
            default=current_value,
            required=True,
            max_length=500 if setting_type != "ai_prompt" else 2000,
            style=(
                discord.TextStyle.paragraph
                if setting_type == "ai_prompt"
                else discord.TextStyle.short
            ),
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Загружаем текущие настройки
            settings = load_bot_settings()
            new_value = self.value_input.value.strip()

            # Обновляем настройку
            if self.setting_type == "ticket_prefix":
                settings["ticket_system"]["channel_prefix"] = new_value
            elif self.setting_type == "min_account_age":
                settings["security"]["min_account_age_days"] = int(new_value)
            elif self.setting_type == "member_count":
                settings["general"]["custom_member_count"] = new_value
            elif self.setting_type == "bot_status":
                settings["general"]["bot_status_text"] = new_value
            elif self.setting_type == "ai_prompt":
                settings["ai"]["custom_system_prompt"] = new_value
            elif self.setting_type == "welcome_message":
                settings["messages"]["welcome_template"] = new_value

            # Сохраняем настройки
            save_bot_settings(settings)

            await interaction.response.send_message(
                f"✅ **Настройка обновлена!**\n\n"
                f"**{self.setting_type}:** `{new_value}`\n\n"
                f"⚠️ Некоторые изменения требуют перезапуска бота для применения.",
                ephemeral=True,
            )

            logger.info(
                f"🔧 {interaction.user.display_name} изменил настройку {self.setting_type}: {new_value}"
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Ошибка: введите корректное числовое значение!", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при сохранении настройки: {e}", ephemeral=True
            )


class ChannelSelectModal(discord.ui.Modal):
    def __init__(self, channel_type: str, current_id: int = None):
        super().__init__(title=f"Настройка канала: {channel_type}")
        self.channel_type = channel_type

        self.channel_input = discord.ui.TextInput(
            label="ID канала",
            placeholder=f"Текущий ID: {current_id or 'не установлен'}",
            default=str(current_id) if current_id else "",
            required=True,
            max_length=20,
        )
        self.add_item(self.channel_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel_id = int(self.channel_input.value.strip())
            channel = interaction.guild.get_channel(channel_id)

            if not channel:
                await interaction.response.send_message(
                    "❌ Канал с таким ID не найден на сервере!", ephemeral=True
                )
                return

            # Загружаем и обновляем настройки
            settings = load_bot_settings()
            settings["channels"][self.channel_type] = channel_id
            save_bot_settings(settings)

            await interaction.response.send_message(
                f"✅ **Канал обновлен!**\n\n"
                f"**{self.channel_type}:** {channel.mention} (`{channel_id}`)",
                ephemeral=True,
            )

            logger.info(
                f"🔧 {interaction.user.display_name} изменил канал {self.channel_type}: {channel.name} ({channel_id})"
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Ошибка: введите корректный ID канала (только цифры)!",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при сохранении канала: {e}", ephemeral=True
            )


class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 Система заявок",
        style=discord.ButtonStyle.primary,
        custom_id="admin_tickets",
    )
    async def ticket_settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(title="📋 Настройки системы заявок", color=0x00FF00)

        settings = load_bot_settings()
        ticket_settings = settings.get("ticket_system", {})

        embed.add_field(
            name="🏷️ Префикс каналов заявок",
            value=f"`{ticket_settings.get('channel_prefix', 'new_')}`",
            inline=False,
        )

        embed.add_field(
            name="⏰ Минимальный возраст аккаунта",
            value=f"{settings.get('security', {}).get('min_account_age_days', 90)} дней",
            inline=False,
        )

        view = TicketSettingsView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="📝 Анкетная форма",
        style=discord.ButtonStyle.success,
        custom_id="admin_form",
    )
    async def form_settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(title="📝 Настройки анкетной формы", color=0x00FF99)

        settings = load_bot_settings()
        form_settings = settings.get("application_form", {})

        # Показываем текущие настройки полей
        fields = form_settings.get("fields", {})

        embed.add_field(
            name="🔗 Поле Steam-профиля",
            value=f"Название: `{fields.get('steam_profile', {}).get('label', '🔗 Ссылка на ваш Steam-профиль')}`\n"
            f"Обязательное: `{fields.get('steam_profile', {}).get('required', True)}`",
            inline=False,
        )

        embed.add_field(
            name="❓ Поле вопросов",
            value=f"Название: `{fields.get('questions', {}).get('label', '❓ Есть ли какие-то вопросы про Деревню нашу?')}`\n"
            f"Обязательное: `{fields.get('questions', {}).get('required', False)}`",
            inline=False,
        )

        view = FormSettingsView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="📺 Каналы",
        style=discord.ButtonStyle.secondary,
        custom_id="admin_channels",
    )
    async def channel_settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(title="📺 Настройки каналов", color=0x0099FF)

        settings = load_bot_settings()
        channels = settings.get("channels", {})

        channel_names = {
            "notification_channel": "🔔 Уведомления",
            "log_channel": "📝 Логи",
            "mod_channel": "👮 Модерация",
            "debug_channel": "🐛 Отладка",
        }

        for key, name in channel_names.items():
            channel_id = channels.get(key)
            if channel_id:
                channel = interaction.guild.get_channel(channel_id)
                value = (
                    f"{channel.mention} (`{channel_id}`)"
                    if channel
                    else f"Канал не найден (`{channel_id}`)"
                )
            else:
                value = "Не настроен"
            embed.add_field(name=name, value=value, inline=False)

        view = ChannelSettingsView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="🤖 Общие настройки",
        style=discord.ButtonStyle.success,
        custom_id="admin_general",
    )
    async def general_settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(title="🤖 Общие настройки бота", color=0x00FF99)

        settings = load_bot_settings()
        general = settings.get("general", {})

        embed.add_field(
            name="👥 Количество участников",
            value=f"`{general.get('custom_member_count', 'Авто')}`",
            inline=False,
        )

        embed.add_field(
            name="📊 Статус бота",
            value=f"`{general.get('bot_status_text', 'за Деревней VLG')}`",
            inline=False,
        )

        view = GeneralSettingsView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="🧠 ИИ настройки", style=discord.ButtonStyle.danger, custom_id="admin_ai"
    )
    async def ai_settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(title="🧠 Настройки ИИ", color=0xFF6600)

        settings = load_bot_settings()
        ai_settings = settings.get("ai", {})

        embed.add_field(name="🎯 Модель ИИ", value=f"`{config.MODEL_ID}`", inline=False)

        custom_prompt = ai_settings.get("custom_system_prompt", "")
        embed.add_field(
            name="📝 Кастомный промпт",
            value=(
                f"`{custom_prompt[:100]}...`"
                if len(custom_prompt) > 100
                else f"`{custom_prompt or 'Не настроен'}`"
            ),
            inline=False,
        )

        view = AISettingsView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="🔄 Обновить панель",
        style=discord.ButtonStyle.gray,
        custom_id="admin_refresh",
    )
    async def refresh_panel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Обновляем основную панель
        updated_embed = create_admin_panel_embed(interaction.guild)
        await interaction.response.edit_message(embed=updated_embed, view=self)


class TicketSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🏷️ Изменить префикс", style=discord.ButtonStyle.primary)
    async def change_prefix(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_prefix = settings.get("ticket_system", {}).get("channel_prefix", "new_")
        modal = AdminSettingsModal("ticket_prefix", current_prefix)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="⏰ Мин. возраст аккаунта", style=discord.ButtonStyle.secondary
    )
    async def change_account_age(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_age = str(settings.get("security", {}).get("min_account_age_days", 90))
        modal = AdminSettingsModal("min_account_age", current_age)
        await interaction.response.send_modal(modal)


class ChannelSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔔 Уведомления", style=discord.ButtonStyle.primary)
    async def set_notification_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_id = settings.get("channels", {}).get("notification_channel")
        modal = ChannelSelectModal("notification_channel", current_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📝 Логи", style=discord.ButtonStyle.secondary)
    async def set_log_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_id = settings.get("channels", {}).get("log_channel")
        modal = ChannelSelectModal("log_channel", current_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="👮 Модерация", style=discord.ButtonStyle.success)
    async def set_mod_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_id = settings.get("channels", {}).get("mod_channel")
        modal = ChannelSelectModal("mod_channel", current_id)
        await interaction.response.send_modal(modal)


class GeneralSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(
        label="👥 Количество участников", style=discord.ButtonStyle.primary
    )
    async def change_member_count(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_count = settings.get("general", {}).get("custom_member_count", "")
        modal = AdminSettingsModal("member_count", current_count)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📊 Статус бота", style=discord.ButtonStyle.secondary)
    async def change_bot_status(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_status = settings.get("general", {}).get(
            "bot_status_text", "за Деревней VLG"
        )
        modal = AdminSettingsModal("bot_status", current_status)
        await interaction.response.send_modal(modal)


class AISettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📝 Кастомный промпт", style=discord.ButtonStyle.primary)
    async def change_ai_prompt(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_prompt = settings.get("ai", {}).get("custom_system_prompt", "")
        modal = AdminSettingsModal("ai_prompt", current_prompt)
        await interaction.response.send_modal(modal)


class FormFieldModal(discord.ui.Modal):
    def __init__(self, field_name: str, current_settings: dict):
        super().__init__(title=f"Настройка поля: {field_name}")
        self.field_name = field_name

        self.label_input = discord.ui.TextInput(
            label="Название поля",
            placeholder="Название которое увидят пользователи",
            default=current_settings.get("label", ""),
            required=True,
            max_length=80,
        )
        self.add_item(self.label_input)

        self.placeholder_input = discord.ui.TextInput(
            label="Подсказка (placeholder)",
            placeholder="Текст-подсказка в поле ввода",
            default=current_settings.get("placeholder", ""),
            required=False,
            max_length=150,
        )
        self.add_item(self.placeholder_input)

        self.required_input = discord.ui.TextInput(
            label="Обязательное поле (да/нет)",
            placeholder="да - обязательное, нет - необязательное",
            default="да" if current_settings.get("required", False) else "нет",
            required=True,
            max_length=3,
        )
        self.add_item(self.required_input)

        self.max_length_input = discord.ui.TextInput(
            label="Максимальная длина",
            placeholder="Максимальное количество символов",
            default=str(current_settings.get("max_length", 200)),
            required=True,
            max_length=4,
        )
        self.add_item(self.max_length_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Загружаем настройки
            settings = load_bot_settings()
            if "application_form" not in settings:
                settings["application_form"] = {"fields": {}}
            if "fields" not in settings["application_form"]:
                settings["application_form"]["fields"] = {}

            # Обновляем настройки поля
            is_required = self.required_input.value.lower().strip() in [
                "да",
                "yes",
                "true",
                "1",
            ]
            max_length = int(self.max_length_input.value.strip())

            settings["application_form"]["fields"][self.field_name] = {
                "label": self.label_input.value.strip(),
                "placeholder": self.placeholder_input.value.strip(),
                "required": is_required,
                "max_length": max_length,
            }

            # Сохраняем настройки
            save_bot_settings(settings)

            await interaction.response.send_message(
                f"✅ **Поле '{self.field_name}' обновлено!**\n\n"
                f"**Название:** `{self.label_input.value.strip()}`\n"
                f"**Подсказка:** `{self.placeholder_input.value.strip()}`\n"
                f"**Обязательное:** `{is_required}`\n"
                f"**Макс. длина:** `{max_length}`\n\n"
                f"⚠️ Изменения применятся при следующем создании формы заявки.",
                ephemeral=True,
            )

            logger.info(
                f"🔧 {interaction.user.display_name} изменил поле формы {self.field_name}"
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Ошибка: введите корректное числовое значение для максимальной длины!",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при сохранении настройки поля: {e}", ephemeral=True
            )


class FormSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔗 Steam-профиль", style=discord.ButtonStyle.primary)
    async def edit_steam_field(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_settings = (
            settings.get("application_form", {})
            .get("fields", {})
            .get("steam_profile", {})
        )
        modal = FormFieldModal("steam_profile", current_settings)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="❓ Вопросы про Деревню", style=discord.ButtonStyle.secondary
    )
    async def edit_questions_field(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        settings = load_bot_settings()
        current_settings = (
            settings.get("application_form", {}).get("fields", {}).get("questions", {})
        )
        modal = FormFieldModal("questions", current_settings)
        await interaction.response.send_modal(modal)


def create_admin_panel_embed(guild):
    """Создает основной embed админ панели"""
    embed = discord.Embed(
        title="🔧 Админ панель VLG бота",
        description=(
            "Панель управления всеми настройками бота.\n"
            "Выберите категорию для настройки:"
        ),
        color=0xFF9900,
    )

    settings = load_bot_settings()

    embed.add_field(
        name="📋 Система заявок",
        value=f"Префикс: `{settings.get('ticket_system', {}).get('channel_prefix', 'new_')}`",
        inline=True,
    )

    embed.add_field(
        name="🤖 Общие настройки",
        value=f"Участников: `{settings.get('general', {}).get('custom_member_count', 'Авто')}`",
        inline=True,
    )

    embed.add_field(name="📺 Каналы", value="Настройка ID каналов", inline=True)

    embed.set_footer(text=f"Сервер: {guild.name} • {guild.member_count} участников")
    return embed


class AdminPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Добавляем постоянные views
        self.bot.add_view(AdminPanelView())

    @app_commands.command(name="check_bot_permissions", description="Проверить права и иерархию ролей бота")
    @app_commands.guild_only()
    async def check_bot_permissions(self, interaction: discord.Interaction):
        """Проверяет права бота и его позицию в иерархии ролей"""
        # Проверяем права
        user_roles = [role.name for role in interaction.user.roles]
        admin_roles = ["Житель", "Гражданин"]
        is_owner = interaction.user.id == interaction.guild.owner_id

        if not any(role in user_roles for role in admin_roles) and not is_owner:
            await interaction.response.send_message(
                "❌ У вас нет прав для проверки прав бота.", ephemeral=True
            )
            return

        guild = interaction.guild
        bot_member = guild.get_member(self.bot.user.id)

        if not bot_member:
            await interaction.response.send_message("❌ Бот не найден на сервере.", ephemeral=True)
            return

        # Получаем информацию о правах бота
        permissions = bot_member.guild_permissions
        bot_top_role = bot_member.top_role

        # Проверяем роли которые бот может изменять
        manageable_roles = []
        unmanageable_roles = []

        important_roles = ["Новичок", "Гость", "Житель", "Гражданин"]
        for role_name in important_roles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                if role < bot_top_role:  # Бот может управлять ролью если она ниже его топ роли
                    manageable_roles.append(role_name)
                else:
                    unmanageable_roles.append(role_name)

        embed = discord.Embed(
            title="🤖 Диагностика прав бота",
            color=0x00FF00 if permissions.manage_nicknames else 0xFF0000,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="🏷️ Информация о боте",
            value=f"**Имя:** {bot_member.display_name}\n**Топ роль:** {bot_top_role.name}\n**Позиция роли:** {bot_top_role.position}",
            inline=False
        )

        embed.add_field(
            name="🔑 Права бота",
            value=f"**Управлять никнеймами:** {'✅' if permissions.manage_nicknames else '❌'}\n"
                  f"**Администратор:** {'✅' if permissions.administrator else '❌'}\n"
                  f"**Управлять ролями:** {'✅' if permissions.manage_roles else '❌'}",
            inline=False
        )

        if manageable_roles:
            embed.add_field(
                name="✅ Может управлять ролями",
                value=", ".join(manageable_roles),
                inline=False
            )

        if unmanageable_roles:
            embed.add_field(
                name="❌ НЕ может управлять ролями",
                value=", ".join(unmanageable_roles) + "\n\n**Решение:** Переместите роль бота выше этих ролей",
                inline=False
            )

        # Проверяем участников с проблемными ролями
        problematic_users = []
        for member in guild.members:
            if member.top_role >= bot_top_role and not member.bot:
                problematic_users.append(f"{member.display_name} ({member.top_role.name})")

        if problematic_users:
            embed.add_field(
                name="⚠️ Участники с ролями выше бота",
                value="\n".join(problematic_users[:10]) + (f"\n... и ещё {len(problematic_users)-10}" if len(problematic_users) > 10 else ""),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin_panel", description="Открыть панель управления ботом"
    )
    @app_commands.guild_only()
    async def admin_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Создает админ панель для управления ботом"""

        # Проверяем права администратора Discord сервера
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ У вас нет прав администратора для доступа к админ панели.",
                ephemeral=True,
            )
            return

        target_channel = channel or interaction.channel

        # Создаем основной embed
        embed = create_admin_panel_embed(interaction.guild)

        # Создаем view с кнопками
        view = AdminPanelView()

        # Отправляем панель
        if channel:
            await target_channel.send(embed=embed, view=view)
            await interaction.response.send_message(
                f"✅ Админ панель создана в {target_channel.mention}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )

        logger.info(
            f"🔧 {interaction.user.display_name} открыл админ панель в {target_channel.name}"
        )

    @app_commands.command(
        name="reload_settings", description="Перезагрузить настройки бота"
    )
    async def reload_settings(self, interaction: discord.Interaction):
        """Перезагружает настройки бота из файла"""

        # Проверяем права администратора Discord сервера
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ У вас нет прав администратора для перезагрузки настроек.",
                ephemeral=True,
            )
            return

        try:
            settings = load_bot_settings()

            await interaction.response.send_message(
                "✅ **Настройки перезагружены!**\n\n"
                "🔄 Некоторые изменения могут требовать перезапуска бота.",
                ephemeral=True,
            )

            logger.info(
                f"🔄 {interaction.user.display_name} перезагрузил настройки бота"
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при перезагрузке настроек: {e}", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminPanel(bot))