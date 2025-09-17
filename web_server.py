"""
Веб-сервер для отображения статуса бота
"""

from flask import Flask, jsonify, render_template_string
import json
import os
from datetime import datetime
import threading
import asyncio
import discord

app = Flask(__name__)

# Глобальные переменные для хранения информации о боте
bot_instance = None
member_count_cache = "3800+"
last_member_count_update = None


def set_bot_instance(bot):
    """Устанавливает экземпляр бота для получения данных о сервере"""
    global bot_instance
    bot_instance = bot


async def get_discord_member_count():
    """Получает актуальное количество участников Discord сервера"""
    global member_count_cache, last_member_count_update

    try:
        if not bot_instance or not bot_instance.is_ready():
            return member_count_cache

        # ID сервера Деревни VLG
        guild_id = 472365787445985280
        guild = bot_instance.get_guild(guild_id)

        if guild and guild.member_count:
            # Форматируем число с пробелами
            formatted_count = f"{guild.member_count:,}".replace(",", " ")
            member_count_cache = formatted_count
            last_member_count_update = datetime.now()
            return formatted_count
        else:
            return member_count_cache

    except Exception as e:
        print(f"❌ Ошибка получения количества участников Discord: {e}")
        return member_count_cache


def update_member_count_sync():
    """Синхронная обертка для обновления количества участников"""
    try:
        if bot_instance and bot_instance.is_ready():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(get_discord_member_count())
        return member_count_cache
    except Exception:
        return member_count_cache


# HTML шаблон для главной страницы
INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Деревня VLG - Самая большая Деревня в RUST</title>
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #2c5530 0%, #1a3d1f 50%, #0f2612 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 15px 40px rgba(0,0,0,0.4);
            text-align: center;
            max-width: 500px;
            width: 100%;
            border: 3px solid #8B4513;
        }
        .village-title {
            background: linear-gradient(45deg, #8B4513, #CD853F, #DEB887);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-size: 1.8em;
            font-weight: bold;
            margin-bottom: 15px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        }
        .village-subtitle {
            color: #2c5530;
            font-size: 1.1em;
            margin-bottom: 25px;
            font-weight: 600;
        }
        .countdown-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 15px;
            padding: 25px;
            margin: 25px 0;
            color: white;
            border: 2px solid #5a67d8;
            box-shadow: 0 8px 32px rgba(102, 126, 234, 0.3);
        }
        .countdown-title {
            font-size: 1.3em;
            margin-bottom: 20px;
            font-weight: bold;
            color: #ffffff;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }
        .countdown {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 15px;
        }
        .countdown-item {
            background: rgba(255,255,255,0.15);
            border-radius: 10px;
            padding: 15px 8px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
            transition: transform 0.2s ease;
        }
        .countdown-item:hover {
            transform: translateY(-2px);
            background: rgba(255,255,255,0.2);
        }
        .countdown-number {
            font-size: 1.6em;
            font-weight: bold;
            display: block;
            color: #ffffff;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }
        .countdown-label {
            font-size: 0.85em;
            opacity: 0.9;
            color: #e2e8f0;
        }
        .status-section {
            background: linear-gradient(135deg, #228B22, #32CD32);
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            color: white;
        }
        .status-online { color: #fff; }
        .status-offline { color: #FFB6C1; }
        .status-unknown { color: #FFFFE0; }
        .status-error { color: #FFB6C1; }
        .bot-status { font-size: 1.3em; font-weight: bold; margin: 10px 0; }
        .last-update { color: rgba(255,255,255,0.8); font-size: 0.9em; margin-top: 10px; }
        .join-btn {
            background: linear-gradient(45deg, #FF6B35, #F7931E);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            cursor: pointer;
            margin-top: 20px;
            font-size: 1.1em;
            font-weight: bold;
            text-decoration: none;
            display: inline-block;
            transition: transform 0.2s;
            box-shadow: 0 4px 15px rgba(255,107,53,0.3);
        }
        .join-btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255,107,53,0.4);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="village-title">🛖 Деревня VLG</div>
        <div class="village-subtitle" id="villageSubtitle">Самая большая Деревня в RUST, где более {{ member_count }} растеров!</div>
        <a href="https://discord.com/invite/MXKVwWQDZS" target="_blank" class="join-btn">
            🎮 Вступить в Деревню
        </a>

        <div class="countdown-container">
            <div class="countdown-title">🛖 Деревня существует уже:</div>
            <div class="countdown">
                <div class="countdown-item">
                    <span class="countdown-number" id="existDays">0</span>
                    <span class="countdown-label">дней</span>
                </div>
                <div class="countdown-item">
                    <span class="countdown-number" id="existHours">0</span>
                    <span class="countdown-label">часов</span>
                </div>
                <div class="countdown-item">
                    <span class="countdown-number" id="existMinutes">0</span>
                    <span class="countdown-label">минут</span>
                </div>
                <div class="countdown-item">
                    <span class="countdown-number" id="existSeconds">0</span>
                    <span class="countdown-label">секунд</span>
                </div>
            </div>
        </div>

        <div class="status-section">
            <div class="bot-status status-{{ status.status }}">
                {% if status.status == 'online' %}
                    🤖 Бот помощник онлайн
                {% elif status.status == 'offline' %}
                    🤖 Бот помощник оффлайн
                {% elif status.status == 'error' %}
                    ⚠️ Ошибка бота
                {% else %}
                    ❓ Статус неизвестен
                {% endif %}
            </div>
            <div class="last-update">
                Обновлено: <span id="lastUpdate">{{ status.last_update }}</span> (Баку)
            </div>
        </div>

    </div>

    <script>
        function updateVillageAge() {
            // Дата основания Деревни: 27 сентября 2023
            const villageFoundation = new Date('2023-09-27T00:00:00');
            const now = new Date();
            const timeDiff = now.getTime() - villageFoundation.getTime();

            if (timeDiff > 0) {
                const days = Math.floor(timeDiff / (1000 * 60 * 60 * 24));
                const hours = Math.floor((timeDiff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                const minutes = Math.floor((timeDiff % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((timeDiff % (1000 * 60)) / 1000);

                document.getElementById('existDays').textContent = days;
                document.getElementById('existHours').textContent = hours;
                document.getElementById('existMinutes').textContent = minutes;
                document.getElementById('existSeconds').textContent = seconds;
            }
        }

        // Обновляем счетчик каждую секунду
        updateVillageAge();
        setInterval(updateVillageAge, 1000);

        // Функция обновления данных
        function updateData() {
            Promise.all([
                fetch('/status').then(response => response.json()),
                fetch('/member_count').then(response => response.json())
            ])
            .then(([statusData, memberData]) => {
                // Обновляем статус
                document.getElementById('lastUpdate').textContent = statusData.last_update;

                // Обновляем количество участников
                if (memberData.member_count) {
                    const subtitle = document.getElementById('villageSubtitle');
                    subtitle.textContent = `Самая большая Деревня в RUST, где более ${memberData.member_count} растеров!`;
                }
            })
            .catch(error => {
                console.log('Обновление данных временно недоступно');
            });
        }

        // Обновляем данные каждые 30 секунд
        setInterval(updateData, 30000);

        // Первичное обновление через 2 секунды после загрузки
        setTimeout(updateData, 2000);
    </script>
</body>
</html>
"""

STATUS_FILE = "status.json"


def load_status():
    """Загрузка данных о статусе"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass

    return {"last_update": "Неизвестно", "status": "unknown"}


def save_status():
    """Сохранение текущего статуса"""
    status_data = {
        "last_update": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "status": "online",
    }

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status_data, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    """Главная страница со статусом бота"""
    try:
        with open("status.json", "r", encoding="utf-8") as f:
            status_data = json.load(f)

        # Получаем актуальное количество участников
        current_member_count = update_member_count_sync()

        return render_template_string(
            INDEX_TEMPLATE, status=status_data, member_count=current_member_count
        )
    except FileNotFoundError:
        return render_template_string(
            INDEX_TEMPLATE,
            status={"last_update": "Неизвестно", "status": "offline"},
            member_count=member_count_cache,
        )
    except Exception as e:
        return render_template_string(
            INDEX_TEMPLATE,
            status={"last_update": "Ошибка загрузки", "status": "error"},
            member_count=member_count_cache,
        )


@app.route("/status")
def status():
    """API для получения статуса бота"""
    try:
        from datetime import timezone, timedelta

        status_data = load_status()

        # Обновляем время на актуальное время Баку
        baku_tz = timezone(timedelta(hours=4))
        baku_time = datetime.now(baku_tz)
        status_data["current_time"] = baku_time.strftime("%d.%m.%Y %H:%M:%S")

        return jsonify(status_data)
    except Exception as e:
        return jsonify(
            {"last_update": "Ошибка загрузки", "status": "error", "error": str(e)}
        )


@app.route("/member_count")
def get_member_count_api():
    """API для получения актуального количества участников Discord"""
    try:
        current_count = update_member_count_sync()
        return jsonify(
            {
                "member_count": current_count,
                "last_update": (
                    last_member_count_update.strftime("%d.%m.%Y %H:%M:%S")
                    if last_member_count_update
                    else "Неизвестно"
                ),
                "source": (
                    "discord_api"
                    if bot_instance and bot_instance.is_ready()
                    else "cache"
                ),
            }
        )
    except Exception as e:
        return jsonify(
            {"member_count": member_count_cache, "error": str(e), "source": "fallback"}
        )


@app.route("/update_status")
def update_status():
    """Обновление статуса (вызывается ботом)"""
    save_status()
    return jsonify({"success": True, "message": "Статус обновлен"})


def run_web_server():
    """Запускает веб-сервер Flask только на порту 5000"""
    import logging
    import socket

    # Отключаем логи werkzeug для чистоты консоли
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Проверяем доступность порта перед запуском
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", 5000))
            if result == 0:
                print("⚠️ Порт 5000 уже занят, веб-сервер не запущен")
                return
    except Exception:
        pass  # Продолжаем попытку запуска

    try:
        print("🌐 web_server: Запуск Flask на порту 5000")
        app.run(
            host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True
        )
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"⚠️ web_server: Порт 5000 уже занят, веб-сервер не запущен")
        else:
            print(f"❌ web_server: Ошибка запуска веб-сервера на порту 5000: {e}")
    except Exception as e:
        print(f"❌ web_server: Ошибка запуска веб-сервера на порту 5000: {e}")


@app.route("/api/status")
def get_status():
    """API для получения статуса бота"""
    try:
        # Читаем файл статуса
        status_data = {}
        try:
            with open("status.json", "r", encoding="utf-8") as f:
                status_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Если файл не найден или поврежден, создаем базовые данные
            status_data = {
                "last_update": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "status": "unknown",
            }

        # Проверяем актуальность данных
        if bot_instance and bot_instance.is_ready():
            status_data["discord_status"] = "online"
            status_data["guild_count"] = len(bot_instance.guilds)
            status_data["user_count"] = sum(
                guild.member_count
                for guild in bot_instance.guilds
                if guild.member_count
            )
        else:
            status_data["discord_status"] = "offline"
            status_data["guild_count"] = 0
            status_data["user_count"] = 0

        return jsonify(status_data)
    except Exception as e:
        print(f"❌ Ошибка получения статуса: {e}")
        return (
            jsonify(
                {
                    "error": "Обновление статуса недоступно",
                    "discord_status": "unknown",
                    "guild_count": 0,
                    "user_count": 0,
                }
            ),
            500,
        )


# Веб-сервер запускается только из bot.py через функцию run_web_server()
# Автозапуск при импорте отключен
if __name__ == "__main__":
    # Этот блок выполнится только при прямом запуске файла
    print("⚠️ web_server.py не должен запускаться напрямую. Используйте bot.py")
    import sys

    sys.exit(1)


def get_bot_status():
    """Получение статуса бота из файла"""
    try:
        if os.path.exists("status.json"):
            with open("status.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "status": data.get("status", "unknown"),
                    "last_update": data.get("last_update", "Никогда"),
                    "guild_count": data.get("guild_count", 0),
                    "member_count": data.get("member_count", 0),
                }
    except Exception as e:
        print(f"Ошибка чтения статуса: {e}")

    return {
        "status": "unknown",
        "last_update": "Неизвестно",
        "guild_count": 0,
        "member_count": 0,
    }
