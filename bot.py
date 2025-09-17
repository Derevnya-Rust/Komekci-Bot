"""
Основной файл Discord бота VLG
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import threading
import json
import os
import time
import traceback
import contextlib
from datetime import datetime, timezone, timedelta
from config import config
from utils.logger import init_logging, setup_logger, get_error_count
from utils.db import create_tables
from utils.discord_logger import discord_logger, log_to_channel, log_error
from utils.kb import load_kb
from utils.rate_limiter import throttled_send

# Инициализируем логирование в самом начале
init_logging()
logger = logging.getLogger(__name__)

@contextlib.contextmanager
def timed(section: str, logger):
    """Контекст-менеджер для измерения времени выполнения"""
    t0 = time.perf_counter()
    try:
        yield
        dt = (time.perf_counter() - t0) * 1000
        logger.debug(f"✅ {section} — готово за {dt:.1f} ms")
    except Exception:
        dt = (time.perf_counter() - t0) * 1000
        logger.error(f"❌ {section} — ошибка спустя {dt:.1f} ms")
        raise

logger.info("=" * 60)
logger.info("🚀 ЗАПУСК DISCORD БОТА VLG")
logger.info("=" * 60)

start_time = time.time()

# Настройка intents
logger.debug("🔧 Настройка Discord intents...")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
logger.debug("✅ Discord intents настроены")

# Создание экземпляра бота
logger.debug("🤖 Создание экземпляра бота...")
bot = commands.Bot(
    command_prefix="/", intents=intents, application_id=config.APPLICATION_ID
)
logger.debug(f"✅ Бот создан с APPLICATION_ID: {config.APPLICATION_ID}")

# Глобальная переменная для отслеживания синхронизации команд
_commands_synced = False
_sync_lock = asyncio.Lock()

# Статистика загрузки
loaded = []
failed = []

async def load_extension_safe(ext: str):
    """Безопасная загрузка расширения с обработкой ошибок"""
    try:
        await bot.load_extension(ext)
        loaded.append(ext)
        logger.debug(f"✅ Загружено расширение: {ext}")
    except Exception as e:
        failed.append((ext, e))
        logger.error(f"❌ Ошибка загрузки расширения {ext}: {e}")


async def setup_hook():
    """Хук настройки - вызывается после подготовки бота, но до входа в систему"""
    global _commands_synced

    # Создание необходимых директорий
    with timed("Создание директорий", logger):
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

    # Валидация конфигурации
    with timed("Валидация конфигурации", logger):
        config.validate()

    # Загрузка всех расширений
    extensions = [
        "handlers.wipes",
        "cogs.roles",
        "cogs.ai",
        "cogs.application_system",
        "cogs.admin_panel",
        "cogs.nickname_admin",
        "cogs.nickname_checker",
        "cogs.kb_sync",
        "handlers.tickets",
    ]

    for ext in extensions:
        await load_extension_safe(ext)

    # Итоговый отчет о загрузке расширений
    logger.info(f"📦 Загружено расширений: {len(loaded)} успешно, {len(failed)} с ошибками")

    # Синхронизация slash-команд (только при необходимости)
    async with _sync_lock:
        if not _commands_synced:
            try:
                # Проверяем, нужна ли синхронизация (файл-маркер)
                sync_needed = not os.path.exists("data/commands_synced.flag") or os.getenv("FORCE_SYNC_COMMANDS") == "true"
                
                if sync_needed:
                    with timed("Синхронизация slash-команд", logger):
                        synced = await asyncio.wait_for(bot.tree.sync(), timeout=30.0)
                        _commands_synced = True
                        logger.info(f"🔄 Синхронизировано команд: {len(synced)}")
                        
                        # Создаем файл-маркер
                        with open("data/commands_synced.flag", "w") as f:
                            f.write(f"synced_{len(synced)}_commands")
                else:
                    _commands_synced = True
                    logger.info("⚡ Пропуск синхронизации команд (уже синхронизированы)")
            except asyncio.TimeoutError:
                logger.warning("⏰ Таймаут синхронизации команд (30с), продолжаем без синхронизации")
            except Exception as e:
                logger.error(f"❌ Ошибка синхронизации команд: {e}")

    # Веб-сервер статуса
    with timed("Запуск веб-сервера", logger):
        start_web_server()

    # Инициализация БД
    with timed("Инициализация БД", logger):
        from utils.db import is_db_available
        await create_tables()
        if not is_db_available():
            logger.info("⚠️ База данных отключена, работаем без неё")

    # Инициализация кешей
    with timed("Инициализация кешей", logger):
        from utils.cache import cache
        cache.info()

    # Инициализация базы знаний
    with timed("Инициализация базы знаний", logger):
        kb_stats = load_kb()
        chunks_count = kb_stats.get('chunks', 0)
        if chunks_count > 0:
            logger.info(f"📚 База знаний: {chunks_count} фрагментов")
        else:
            logger.info("📚 База знаний пуста")


# Устанавливаем setup_hook
bot.setup_hook = setup_hook


def update_bot_status():
    """Обновление статуса бота в файле"""
    # Время по Баку (UTC+4)
    baku_tz = timezone(timedelta(hours=4))
    baku_time = datetime.now(baku_tz)

    # Получаем данные о сервере если бот готов
    guild_count = 0
    member_count = 0

    if bot.is_ready() and bot.guilds:
        guild_count = len(bot.guilds)
        member_count = sum(guild.member_count or 0 for guild in bot.guilds)

    status_data = {
        "last_update": baku_time.strftime("%d.%m.%Y %H:%M:%S"),
        "status": "online" if bot.is_ready() else "starting",
        "guild_count": guild_count,
        "member_count": member_count,
    }

    try:
        with open("status.json", "w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"📊 Статус бота обновлен")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса: {e}")


# Глобальные переменные для отслеживания состояния
_web_server_started = False
_web_server_lock = threading.Lock()


def start_web_server():
    """Запуск веб-сервера в отдельном потоке с защитой от дублирования"""
    global _web_server_started

    with _web_server_lock:
        if _web_server_started:
            logger.debug("🌐 Веб-сервер уже запущен, пропускаем")
            return

        try:
            from web_server import run_web_server, set_bot_instance

            set_bot_instance(bot)
            server_thread = threading.Thread(
                target=run_web_server, daemon=True, name="WebServer"
            )
            server_thread.start()
            _web_server_started = True
            logger.info("🌐 Веб-сервер статуса запущен на порту 5000")
        except Exception as e:
            logger.error(f"❌ Ошибка запуска веб-сервера: {e}")
            _web_server_started = False


@bot.event
async def on_connect():
    """Событие подключения к Discord"""
    logger.debug("🔌 Discord: on_connect")

@bot.event
async def on_ready() -> None:
    """Событие готовности бота"""
    total_time = time.time() - start_time

    try:
        guilds = len(bot.guilds)
        users = sum(g.member_count or 0 for g in bot.guilds)
    except Exception:
        guilds, users = len(bot.guilds), 0

    latency_ms = bot.latency * 1000 if getattr(bot, "latency", None) else 0

    logger.info("=" * 60)
    logger.info("🎉 БОТ ГОТОВ К РАБОТЕ!")
    logger.info("=" * 60)
    logger.info(f"🤖 Имя бота: {bot.user}")
    logger.info(f"🆔 ID бота: {bot.user.id if bot.user else 'Unknown'}")
    logger.info(f"🟢 Бот готов: гильдий={guilds}, участников~={users}, latency={latency_ms:.0f} ms")

    if bot.guilds:
        for guild in bot.guilds:
            logger.debug(f"   🏠 {guild.name}: {guild.member_count} участников")

    # Инициализируем Discord логгер
    discord_logger.set_bot(bot)

    # Обновляем логгер с ботом для Discord handler
    setup_logger(bot)

    # Логируем запуск бота в Discord канал
    discord_logger.info(f"🚀 Бот запущен: {bot.user}")

    # Инициализация AutoResponseHandler
    try:
        from handlers.auto_response import AutoResponseHandler
        auto_response_handler = AutoResponseHandler(bot)
        bot._auto_response_handler = auto_response_handler
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации AutoResponseHandler: {e}")

    # Регистрация persistent views для кнопок заявок
    try:
        # Импортируем views из разных модулей
        from handlers.novichok_actions import (
            TicketActionView, RecheckApplicationView
        )
        from cogs.application_system import (
            ApplicationButton, DeleteApplicationView, ReadyButtonView, ConfirmDeleteView
        )
        from handlers.tickets import NicknameMismatchFixView

        # Регистрируем все persistent views БЕЗ параметров для правильной работы после рестарта
        bot.add_view(ApplicationButton())
        bot.add_view(DeleteApplicationView())
        bot.add_view(ReadyButtonView())
        bot.add_view(TicketActionView())
        bot.add_view(RecheckApplicationView())
        bot.add_view(NicknameMismatchFixView())
        bot.add_view(ConfirmDeleteView())

        logger.info("✅ Постоянные view (кнопки заявок) зарегистрированы")
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации persistent views: {e}")

    # Установка статуса бота
    update_bot_status()

    logger.info("=" * 60)
    logger.info("🟢 БОТ ПОЛНОСТЬЮ ЗАПУЩЕН И ГОТОВ К РАБОТЕ")
    logger.info("=" * 60)

    # Финальное сообщение с временем запуска и ошибками
    error_count = get_error_count()
    logger.info(f"⏱️ Время запуска: {total_time:.2f} c | ✅ Бот успешно запущен | Проблем выявлено: {error_count}")


@bot.event
async def on_message(message: discord.Message) -> None:
    """Обработка сообщений"""
    if message.author.bot or message.author == bot.user:
        return

    # ВАЖНО: AI канал обрабатывается ТОЛЬКО в cogs/ai.py
    if message.channel.id == config.AI_RESPONSE_CHANNEL_ID:
        await bot.process_commands(message)
        return

    # Обработка автоответов в тикетах
    try:
        auto_response_handler = getattr(bot, "_auto_response_handler", None)
        if auto_response_handler:
            await auto_response_handler.handle_message(message)
    except Exception as e:
        logger.error(f"❌ Ошибка обработки автоответа: {e}")

    # Простой ответ на упоминание (если это не тикет-канал)
    if bot.user in message.mentions and not (
        hasattr(message.channel, "name")
        and getattr(message.channel, "name", "").startswith(config.TICKET_CHANNEL_PREFIX)
    ):
        try:
            await throttled_send(
                message.channel,
                f"👋 Привет, {message.author.mention}! "
                f"Я помощник Деревни VLG. Если у вас есть вопросы - обращайтесь!",
            )
        except Exception as e:
            logger.error(f"❌ Ошибка ответа на упоминание: {e}")

    # Обработка команд
    await bot.process_commands(message)


@bot.event
async def on_interaction(interaction: discord.Interaction) -> None:
    """Логирование взаимодействий"""
    if interaction.type == discord.InteractionType.application_command:
        command_name = interaction.command.name if interaction.command else "unknown"
        logger.debug(f"⚡ Команда: /{command_name} от {interaction.user}")

    elif interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get('custom_id', 'unknown') if interaction.data else 'unknown'
        logger.debug(f"🎛️ Компонент: {custom_id} от {interaction.user}")


@bot.event
async def on_error(event: str, *args, **kwargs) -> None:
    """Обработка ошибок бота"""
    error_msg = traceback.format_exc()
    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в событии {event}:")
    logger.error(error_msg)

    # Логируем критические ошибки в Discord канал
    try:
        await log_error(Exception(f"Ошибка в событии {event}"), error_msg[:500])
    except Exception as log_error_ex:
        logger.error(f"❌ Не удалось залогировать ошибку: {log_error_ex}")


@bot.tree.command(
    name="sync_commands",
    description="Пересинхронизировать slash-команд (только для админов)",
)
@app_commands.guild_only()
async def sync_commands(interaction: discord.Interaction):
    """Пересинхронизация slash-команд"""
    # Проверяем права администратора
    if not (hasattr(interaction.user, 'guild_permissions') and
            getattr(interaction.user, 'guild_permissions', None) and
            interaction.user.guild_permissions.administrator):
        await interaction.response.send_message(
            "❌ У вас нет прав для синхронизации команд.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        # Синхронизируем команды для текущей гильдии
        synced = await bot.tree.sync(guild=interaction.guild)
        await interaction.followup.send(
            f"✅ **Команды синхронизированы!**\n\n"
            f"📊 Синхронизировано команд: **{len(synced)}**",
            ephemeral=True,
        )
        logger.info(f"🔄 {interaction.user.display_name} пересинхронизировал {len(synced)} команд")
    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации команд: {e}")
        await interaction.followup.send(
            f"❌ Произошла ошибка при синхронизации команд: {str(e)}", ephemeral=True
        )


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    """Обработка ошибок slash-команд"""
    command_name = interaction.command.name if interaction.command else "unknown"

    try:
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            logger.warning(f"⏰ Команда /{command_name}: кулдаун ({error.retry_after:.2f}с)")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Команда на кулдауне. Попробуйте через {error.retry_after:.2f} секунд.",
                    ephemeral=True,
                )
        elif isinstance(error, discord.app_commands.MissingPermissions):
            logger.warning(f"🚫 Команда /{command_name}: нет прав у {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "У вас нет прав для использования этой команды.", ephemeral=True
                )
        else:
            logger.error(f"❌ Ошибка в команде /{command_name}: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Произошла ошибка при выполнении команды.", ephemeral=True
                )
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в обработчике ошибок slash-команд: {e}")


async def init_database():
    """Инициализация базы данных"""
    try:
        await create_tables()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.warning(f"⚠️ База данных недоступна, продолжаем без неё: {e}")


async def main():
    """Основная функция запуска"""
    try:
        # Создание необходимых директорий
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

        # Валидация конфигурации
        config.validate()

        # Настройка обработчика сигналов для graceful shutdown
        def signal_handler(signum, frame):
            logger.info(f"🔴 Получен сигнал {signum}, завершение работы...")
            asyncio.create_task(bot.close())

        import signal
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        await bot.start(config.DISCORD_TOKEN)
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка запуска: {e}\n{traceback.format_exc()}")
        raise


if __name__ == "__main__":
    asyncio.run(main())