import os
from typing import Optional, List


class Config:
    """Централизованная конфигурация бота"""

    # Discord
    DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
    APPLICATION_ID: int = 1385027874313994340

    # Steam API
    STEAM_API_KEY: Optional[str] = os.getenv("STEAM_API_KEY")

    # AI APIs
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    MODEL_ID: str = os.getenv("MODEL_ID", "meta-llama/llama-4-scout-17b-16e-instruct")

    # Web server
    ENABLE_WEB_SERVER: bool = os.getenv("ENABLE_WEB_SERVER", "false").lower() == "true"

    # Database (Supabase)
    DB_HOST: Optional[str] = os.getenv("DB_HOST")
    DB_PORT: Optional[str] = os.getenv("DB_PORT", "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME")
    DB_USER: Optional[str] = os.getenv("DB_USER")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD")

    # Channel IDs
    NOTIFICATION_CHANNEL_ID: int = 1178436876244361388
    LOG_CHANNEL_ID: int = 1290429444955181137  # Все логи теперь идут в один канал
    PERSONAL_CHANNEL_ID: int = 1226224193603895386
    AI_RESPONSE_CHANNEL_ID: int = 1178436876244361388
    MOD_CHANNEL_ID: int = 1225005174800519208
    DEBUG_CHANNEL_ID: int = 1290429444955181137
    RULES_CHANNEL_ID: int = 1179490341980741763
    KB_CHANNEL_ID: int = 1322342577239756881
    IDEAS_CHANNEL_ID: int = 1271930925089030144
    VOTING_CHANNEL_ID: int = 1176931782935986249
    MODERATOR_REQUESTS_CHANNEL_ID: int = 1178106335716446228
    TICKETS_CATEGORY_ID: int = 472365787445985280  # Используется в embed links
    WIPE_INFO_CHANNEL_ID: int = 1186254344820113409
    TEAM_SEARCH_CHANNEL_ID: int = 1264874500693037197
    RAID_ORGANIZATION_CHANNEL_ID: int = 1190252389459042355
    STAROSTA_REQUESTS_CHANNEL_ID: int = 1238117981939171368
    BOOSTERS_THANKS_CHANNEL_ID: int = 1409287924041781278

    # Ticket system
    TICKET_CHANNEL_PREFIX: str = "new_"

    # Role configurations
    ALLOWED_ROLES: List[str] = ["Прохожий", "Новичок"]
    MODERATOR_ROLES: List[str] = ["Гражданин", "Ополчение"]
    EXCLUSIVE_ROLES: List[str] = ["Зам.Коменданта[О]", "Офицер"]
    MILITARY_ROLES: List[str] = ["Солдат", "Боец", "Сержант"]
    ASSIGNABLE_ROLES: List[str] = ["Прохожий", "Житель", "Гражданин"]
    ADMIN_ROLES: List[str] = [
        "Гражданин",
        "Ополчение",
        "Зам.Коменданта[О]",
        "Офицер",
        "Администратор",
    ]

    # Role IDs
    NEWBIE_ROLE_ID: int = 1257813489595191296  # ID роли "Новичок"
    GUEST_ROLE_ID: int = 1274498693172822048  # ID роли "Прохожий"
    STAROSTA_ROLE_ID: int = 1200959962403324016  # ID роли "Староста"
    KOMENDATURA_ROLE_ID: int = 1187109902292885514  # ID роли "Комендатура"
    HIGH_ACTIVITY_ROLE_ID: int = 1333173647539441735  # Высокий уровень активности
    MEDIUM_ACTIVITY_ROLE_ID: int = 1333174173274738790  # Средний уровень активности
    LOW_ACTIVITY_ROLE_ID: int = 1333174250110058556  # Низкий уровень активности
    ADMINISTRATOR_ROLE_ID: int = 1178690166043963473  # Администратор
    OFFICER_ROLE_ID: int = 1178689858251997204  # Офицер

    # Optional role IDs
    CITIZEN_ROLE_ID: Optional[int] = int(os.getenv("CITIZEN_ROLE_ID", "0")) or None


    # Security settings
    SECURITY_ENABLED = True
    MAX_MESSAGE_LENGTH = 2000

    # FIX: повысим задержку между LLM-вызовами
    LLM_DELAY_MULTIPLIER = 2

    # Cache settings
    DEFAULT_CACHE_TTL: int = 300  # 5 minutes
    STEAM_CACHE_TTL: int = 300  # 5 minutes
    AI_CACHE_TTL: int = 300  # 5 minutes

    # Debug settings
    DEBUG_NICKNAME_CHECKS: bool = True  # Включить подробные логи проверки ников
    DEBUG_AI_MODERATION: bool = True    # Включить подробные логи AI модерации

    # Rate limiting
    STEAM_RATE_LIMIT_PER_SECOND: int = 1
    STEAM_RATE_LIMIT_PER_5MIN: int = 100
    AI_RATE_LIMIT_PER_USER = 3  # запросов за период
    AI_RATE_LIMIT_PERIOD = 60  # период в секундах

    # Knowledge Base
    KB_CHANNEL_IDS = [1322342577239756881, 1179490341980741763]
    KB_PATH = "data/kb.json"

    # Nickname moderation
    NICKCHECK_ALWAYS_USE_LLM: bool = True
    NICKCHECK_PROVIDER: str = "openrouter"  # "openrouter" | "groq"
    NICKCHECK_MODEL: str = "openrouter/auto"
    NICK_AUTO_APPLY_FIXED: bool = True  # разрешить кнопку «Применить исправление»
    NICK_SHOW_TECH_ERRORS_TO_USER: bool = False  # не показывать технические ошибки LLM пользователям
    LLM_MIN_DELAY_SECONDS: float = 3.2  # базовая задержка между LLM-запросами (сек), удвоена с 1.6

    @classmethod
    def validate(cls) -> None:
        """Проверить обязательные переменные окружения"""
        if not cls.DISCORD_TOKEN:
            raise ValueError("DISCORD_TOKEN не установлен в переменных окружения")

        missing_keys = []
        if not cls.STEAM_API_KEY:
            missing_keys.append("STEAM_API_KEY")
        if not cls.GROQ_API_KEY and not cls.OPENROUTER_API_KEY:
            missing_keys.append("GROQ_API_KEY или OPENROUTER_API_KEY")

        if missing_keys:
            print(f"⚠️ Отсутствуют ключи API: {', '.join(missing_keys)}")
            print("Некоторые функции могут работать некорректно")


# Глобальный экземпляр конфигурации
config = Config()