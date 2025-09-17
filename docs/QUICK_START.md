
# 🚀 Быстрый старт - Discord Bot VLG

## ⚡ Минимальная настройка (5 минут)

### 1. Переменные окружения (Replit Secrets):
```bash
DISCORD_TOKEN=your_bot_token_here
STEAM_API_KEY=your_steam_api_key
GROQ_API_KEY=your_groq_api_key
```

### 2. Права бота в Discord:
- ✅ Use Slash Commands
- ✅ Send Messages  
- ✅ Manage Roles
- ✅ View Channels

### 3. Запуск:
```bash
python bot.py
```

## 📋 Проверка работы:

1. **Slash команды:** `/info` - информация о пользователе
2. **AI помощник:** `/text Привет!` - тест AI
3. **Управление ролями:** `/role @user Новичок` (для модераторов)

## 🔧 Настройка каналов:

В `config.py` укажите ID ваших каналов:
```python
NOTIFICATION_CHANNEL_ID = 123456789  # Канал уведомлений
LOG_CHANNEL_ID = 123456789          # Канал логов
MOD_CHANNEL_ID = 123456789          # Канал модераторов
```

## ❓ Проблемы?

- **Команды не работают:** Проверьте синхронизацию (`await bot.tree.sync()`)
- **Нет Steam данных:** Проверьте STEAM_API_KEY
- **AI не отвечает:** Проверьте GROQ_API_KEY

---
📖 **Полная документация:** `docs/DOCUMENTATION.md`
