
import json
import os
import logging
from typing import List, Dict, Any
from config import config

logger = logging.getLogger(__name__)

# Глобальная база знаний
_kb_data = {"chunks": [], "faq": []}
_kb_loaded = False


class KnowledgeBase:
    """Класс для работы с базой знаний"""
    
    def __init__(self):
        self.data = {"chunks": [], "faq": []}
    
    def get_all_fragments(self) -> List[str]:
        """Получить все фрагменты базы знаний"""
        fragments = []
        if self.data.get("chunks"):
            fragments.extend([chunk.get("content", "") for chunk in self.data["chunks"] if isinstance(chunk, dict)])
        if self.data.get("faq"):
            fragments.extend([faq.get("answer", "") for faq in self.data["faq"] if isinstance(faq, dict)])
        return fragments
    
    def add_fragment(self, text: str):
        """Добавить фрагмент в базу знаний"""
        if not text or len(text.strip()) < 10:
            return False
            
        fragment = {
            "content": text.strip(),
            "created_at": "",
            "source": "manual"
        }
        self.data["chunks"].append(fragment)
        return self.save()
    
    def save(self) -> bool:
        """Сохранить базу знаний в файл"""
        return save_kb()


# Глобальный экземпляр базы знаний
kb = KnowledgeBase()


def load_kb() -> Dict[str, Any]:
    """Загрузка базы знаний из файла"""
    global _kb_data, _kb_loaded
    
    try:
        if os.path.exists(config.KB_PATH):
            with open(config.KB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # Обработка разных форматов данных
                if isinstance(data, list):
                    # Если это список сообщений из каналов
                    _kb_data = {"chunks": [], "faq": []}
                    for item in data:
                        if isinstance(item, dict) and item.get("text"):
                            # Разбиваем длинные сообщения на фрагменты
                            text = item["text"].strip()
                            if len(text) > 50:  # Минимальная длина фрагмента
                                _kb_data["chunks"].append({
                                    "content": text,
                                    "channel_id": item.get("cid"),
                                    "message_id": item.get("id")
                                })
                elif isinstance(data, dict):
                    # Если это уже структурированная база знаний
                    _kb_data = data
                    if "chunks" not in _kb_data:
                        _kb_data["chunks"] = []
                    if "faq" not in _kb_data:
                        _kb_data["faq"] = []
                else:
                    # Неизвестный формат - создаем пустую базу
                    _kb_data = {"chunks": [], "faq": []}
                
                kb.data = _kb_data
                _kb_loaded = True
        else:
            # Создаем пустую базу знаний
            _kb_data = {"chunks": [], "faq": []}
            kb.data = _kb_data
            _kb_loaded = True
            logger.debug("📚 Файл базы знаний не найден, создана пустая база")
            
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки базы знаний: {e}")
        _kb_data = {"chunks": [], "faq": []}
        kb.data = _kb_data
        _kb_loaded = True
    
    chunks_count = len(_kb_data.get("chunks", []))
    faq_count = len(_kb_data.get("faq", []))
    
    return {
        "chunks": chunks_count,
        "faq": faq_count,
        "total": chunks_count + faq_count,
        "loaded": _kb_loaded
    }


def ensure_kb_loaded():
    """Убеждается что база знаний загружена"""
    global _kb_loaded
    if not _kb_loaded:
        load_kb()


def get_context(query: str, k: int = 5) -> List[str]:
    """Получить контекст для запроса"""
    ensure_kb_loaded()
    
    # Простой поиск по ключевым словам
    query_lower = query.lower()
    results = []
    
    for chunk in _kb_data.get("chunks", []):
        if isinstance(chunk, dict):
            content = chunk.get("content", "")
            if any(word in content.lower() for word in query_lower.split()):
                results.append(content[:500])  # Ограничиваем длину
    
    for faq in _kb_data.get("faq", []):
        if isinstance(faq, dict):
            question = faq.get("question", "")
            answer = faq.get("answer", "")
            if any(word in question.lower() or word in answer.lower() for word in query_lower.split()):
                results.append(f"Q: {question}\nA: {answer}")
    
    return results[:k]


def save_kb() -> bool:
    """Сохранение базы знаний в файл"""
    try:
        os.makedirs(os.path.dirname(config.KB_PATH), exist_ok=True)
        with open(config.KB_PATH, "w", encoding="utf-8") as f:
            json.dump(_kb_data, f, ensure_ascii=False, indent=2)
        logger.debug("📚 База знаний сохранена")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения базы знаний: {e}")
        return False


async def update_from_channels(bot) -> Dict[str, int]:
    """Обновление базы знаний из Discord каналов"""
    global _kb_data
    stats = {"messages": 0}
    new_chunks = []
    
    try:
        for channel_id in config.KB_CHANNEL_IDS:
            channel = bot.get_channel(channel_id)
            if channel:
                message_count = 0
                async for message in channel.history(limit=100):
                    if message.content and len(message.content) > 50:
                        new_chunks.append({
                            "content": message.content.strip(),
                            "channel_id": channel_id,
                            "message_id": message.id,
                            "created_at": message.created_at.isoformat()
                        })
                        message_count += 1
                
                stats["messages"] += message_count
                logger.debug(f"📚 Обработано сообщений из #{channel.name}: {message_count}")
        
        # Обновляем базу знаний
        _kb_data["chunks"] = new_chunks
        kb.data = _kb_data
        
        # Сохраняем в файл
        save_kb()
        
        stats["chunks"] = len(new_chunks)
    
    except Exception as e:
        logger.error(f"❌ Ошибка обновления базы знаний: {e}")
    
    return stats
