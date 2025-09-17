
import os
import logging

logger = logging.getLogger(__name__)

# Глобальная переменная состояния БД
_db_available = False


def is_db_available() -> bool:
    """Проверка доступности базы данных"""
    return _db_available


async def create_tables():
    """Создание таблиц БД (опционально)"""
    global _db_available
    
    try:
        # Проверяем наличие всех необходимых переменных окружения БД
        if not all([
            os.getenv("DB_HOST"),
            os.getenv("DB_USER"), 
            os.getenv("DB_PASSWORD"),
            os.getenv("DB_NAME")
        ]):
            logger.warning("⚠️ База данных отключена, работаем без неё")
            _db_available = False
            return
        
        # Пытаемся подключиться к БД
        try:
            import asyncpg
            conn = await asyncpg.connect(
                host=os.getenv("DB_HOST"),
                port=int(os.getenv("DB_PORT", "5432")),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME"),
            )
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT NOT NULL,
                    steam_url TEXT,
                    steam_id64 TEXT,
                    experience TEXT,
                    invited_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            await conn.close()
            _db_available = True
            logger.info("✅ База данных подключена и инициализирована")
            
        except ImportError:
            logger.warning("⚠️ База данных отключена, работаем без неё (asyncpg не установлен)")
            _db_available = False
        except Exception as e:
            logger.warning(f"⚠️ База данных отключена, работаем без неё: {e}")
            _db_available = False
            
    except Exception as e:
        logger.warning(f"⚠️ База данных отключена, работаем без неё: {e}")
        _db_available = False


async def save_application(discord_id, steam_url, steam_id64, experience, invited_by):
    """Сохранение заявки в БД (опционально)"""
    if not _db_available:
        logger.debug(f"Заявка для {discord_id} (БД не используется)")
        return None
        
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
        )
        
        result = await conn.fetchrow("""
            INSERT INTO applications (discord_id, steam_url, steam_id64, experience, invited_by)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, discord_id, steam_url, steam_id64, experience, invited_by)
        
        await conn.close()
        logger.debug(f"Заявка сохранена в БД с ID: {result['id']}")
        return result['id']
        
    except Exception as e:
        logger.debug(f"Ошибка сохранения заявки в БД: {e}")
        return None


async def init_database():
    """Псевдоним для create_tables"""
    await create_tables()
