ЗАДАЧА: добавить локальную базу знаний (RAG) из двух каналов Discord и заставить AI отвечать только на основе этих данных. Каналы:

* Всё-про-Деревню: `1322342577239756881`
* Правила-Деревни: `1179490341980741763`

## 1) Конфиг

Открой `config.py`. В конец класса `Config` добавь:

```python
    # Knowledge Base
    KB_CHANNEL_IDS = [1322342577239756881, 1179490341980741763]
    KB_PATH = "data/kb.json"
```

## 2) Утилита БЗ

Создай файл `utils/kb.py`:

```python
import os, json, re, math, asyncio, datetime
import discord
from collections import Counter, defaultdict
from typing import List, Dict, Tuple
from config import config

# Глобальный индекс в памяти
_KB = {"chunks": [], "meta": [], "idf": {}, "vectors": [], "norms": []}
_LOADED = False

def _normalize(text: str) -> List[str]:
    text = text.lower().replace("ё","е")
    tokens = re.findall(r"[a-zа-я0-9]{2,}", text)
    return tokens

def _chunk_text(text: str, max_len: int = 700) -> List[str]:
    text = text.strip()
    if len(text) <= max_len:
        return [text]
    parts = re.split(r"(?<=[\.\!\?])\s+", text)
    chunks, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= max_len:
            cur = (cur + " " + p).strip()
        else:
            if cur: chunks.append(cur)
            cur = p
    if cur: chunks.append(cur)
    return [c for c in chunks if len(c) >= 60]

def _build_index(chunks: List[str]):
    # df → idf
    docs_tokens = [Counter(_normalize(c)) for c in chunks]
    df = defaultdict(int)
    for tokset in [set(d.keys()) for d in docs_tokens]:
        for t in tokset: df[t]+=1
    N = max(1, len(chunks))
    idf = {t: math.log((N+1)/(df_t+1)) + 1.0 for t, df_t in df.items()}
    # векторы и нормы
    vectors, norms = [], []
    for d in docs_tokens:
        v = {t: (d[t] * idf.get(t, 0.0)) for t in d}
        n = math.sqrt(sum(x*x for x in v.values())) or 1.0
        vectors.append(v); norms.append(n)
    return idf, vectors, norms

def _load_file():
    path = config.KB_PATH
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_kb():
    global _KB, _LOADED
    rows = _load_file()
    chunks, meta = [], []
    for r in rows:
        cid = r.get("cid"); txt = r.get("text","").strip()
        if not txt: continue
        for ch in _chunk_text(txt):
            chunks.append(ch)
            meta.append({"cid": cid})
    idf, vectors, norms = _build_index(chunks) if chunks else ({},[],[])
    _KB = {"chunks": chunks, "meta": meta, "idf": idf, "vectors": vectors, "norms": norms}
    _LOADED = True
    return {"messages": len(rows), "chunks": len(chunks)}

def ensure_kb_loaded():
    if not _LOADED:
        load_kb()

def _cosine_score(qv: Dict[str,float], dv: Dict[str,float], dnorm: float) -> float:
    if not dv: return 0.0
    s = 0.0
    for t, w in qv.items():
        if t in dv: s += w * dv[t]
    qn = math.sqrt(sum(w*w for w in qv.values())) or 1.0
    return s / (qn * dnorm)

def _query_vector(q: str, idf: Dict[str,float]) -> Dict[str,float]:
    tf = Counter(_normalize(q))
    return {t: tf[t]*idf.get(t, 0.0) for t in tf}

def get_context(query: str, k: int = 8) -> List[str]:
    ensure_kb_loaded()
    if not _KB["chunks"]:
        return []
    idf, vectors, norms = _KB["idf"], _KB["vectors"], _KB["norms"]
    qv = _query_vector(query, idf)
    scores = []
    for i, dv in enumerate(vectors):
        s = _cosine_score(qv, dv, norms[i])
        if s > 0: scores.append((s, i))
    scores.sort(reverse=True)
    top = [i for _, i in scores[:k]]
    name = {config.KB_CHANNEL_IDS[0]: "Всё про Деревню", config.KB_CHANNEL_IDS[1]: "Правила Деревни"}
    out = []
    used = set()
    for idx in top:
        ch = _KB["chunks"][idx].strip()
        md = _KB["meta"][idx]
        key = (md.get("cid"), ch[:80])
        if key in used: continue
        used.add(key)
        out.append(f"[{name.get(md.get('cid'),'Раздел')}] {ch}")
    return out

async def update_from_channels(bot: discord.Client) -> Dict[str,int]:
    os.makedirs(os.path.dirname(config.KB_PATH), exist_ok=True)
    rows = []
    for cid in config.KB_CHANNEL_IDS:
        ch = bot.get_channel(cid)
        if ch is None:  # попытка через fetch
            try:
                ch = await bot.fetch_channel(cid)
            except Exception:
                continue
        async for m in ch.history(limit=None, oldest_first=True):
            if not m.content: continue
            rows.append({
                "cid": cid,
                "id": m.id,
                "t": m.created_at.isoformat(),
                "text": m.content
            })
    with open(config.KB_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0)
    stats = load_kb()
    return stats
```

## 3) Слэш-команда синхронизации

Создай `cogs/kb_sync.py`:

```python
import discord
from discord.ext import commands
from discord import app_commands
from utils.kb import update_from_channels, load_kb

class KBSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync_kb", description="Обновить базу знаний из каналов Деревни")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sync_kb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        stats = await update_from_channels(self.bot)
        await interaction.followup.send(
            f"Готово. Сообщений: {stats.get('messages',0)}. Фрагментов: {stats.get('chunks',0)}.",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(KBSync(bot))
```

## 4) Подключить ког

Открой `bot.py`, в списке `extensions` добавь строку `"cogs.kb_sync",` и убедись, что создаётся папка `data/` при старте, если её нет:

```python
os.makedirs("data", exist_ok=True)
```

(добавь перед запуском бота).

## 5) Включить RAG в AI

Правь `cogs/ai.py`:

* Вверху импортируй:
  `from utils.kb import ensure_kb_loaded, get_context`
* В обработчике `on_message` после получения `system_context`, `user_context` и перед формированием `full_prompt` добавь:

```python
        # --- RAG: вытаскиваем релевант из БЗ ---
        ensure_kb_loaded()
        ctx_chunks = get_context(user_message, k=8)
        context_text = "\n\n".join(ctx_chunks) if ctx_chunks else ""
        guard = (
            "\nПравило ответа: отвечай ТОЛЬКО по Контексту ниже. "
            "Если в Контексте нет ответа, скажи: "
            "\"Не нашёл в правилах/разделах Деревни. Обратитесь в Комендатуру.\""
        )
        # если контекст пуст, сразу отказ
        if not context_text:
            reply = "Не нашёл в правилах/разделах Деревни. Обратитесь в Комендатуру."
            await throttled_send(message.channel, f"{message.author.mention} {reply}")
            return
```

* Сформируй `full_prompt` так:

```python
        full_prompt = (
            f"{system_context}{guard}\n\n"
            f"КОНТЕКСТ:\n{context_text}\n\n"
            f"{user_context}{wipe_info}\n\n"
            f"Вопрос пользователя: {user_message}"
        )
```

## 6) Безопасные ответы

В `cogs/ai_brain.py` в `SYSTEM_PROMPT` уже есть защита. Ничего не менять, но проверь, что есть фраза вида: «если нет фактов — откажись». Если нет, добавь её.

## 7) Права и запуск

* Дай боту права Read Messages и Read Message History на оба канала.
* Создай папку `data/` в корне.
* Перезапусти деплой.
* В Discord выполни `/sync_kb`. Убедись, что в `data/kb.json` появились записи.

## 8) Проверка

* В AI-канале спроси: «Сколько вайпов нужно до Жителя?» Ответ должен прийти из контекста.
* Спроси что-то вне правил. Бот должен ответить шаблоном отказа.

Сделай все правки строго по этим инструкциям.
