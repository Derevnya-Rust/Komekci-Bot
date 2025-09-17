# handlers/wipes.py
# -*- coding: utf-8 -*-
import os
import json
import datetime as dt
import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.logger import get_module_logger

logger = get_module_logger(__name__)

# ================== КОНСТАНТЫ И НАСТРОЙКИ ==================
TZ = dt.timezone(dt.timedelta(hours=4))  # Asia/Baku (UTC+4)

CONFIG_PATH = "wipes_config.json"
DEFAULTS = {
    "enabled": False,
    "channel_id": None,
    # Время старта вайпа по Баку: 18:00 = 17:00 МСК (можно менять через панель)
    "start_time": "17:00",
    # Глобальный номер следующего вайпа (увеличится после T-1m)
    "wipe_no": 192,
    # Антидубли по этапам (сохраняем YYYY-MM-DD дня отправки)
    "last_pre_date": "",  # T-24h (воскресенье/среда)
    "last_hour_date": "",  # T-1h  (понедельник/четверг)
    "last_minute_date": "",  # T-1m  (понедельник/четверг)
    "last_inc_date": "",  # безопасный инкремент номера вайпа (Чтобы не потерять инкремент, если бот был офлайн в 16:59)
    # Окно допуска (минуты) чтобы не пропускать триггер
    "window_minutes": 5,
    # Настройки бустеров
    "boosters_realtime_enabled": False,
    "boosters_realtime_channel_id": None,
    "boosters_role_id": None,
    "boosters_allowed_roles": [],
    "last_thanks_ym": "",
}

SERVERS = {
    "monday": {
        "label": "RustResort.com - EU Monday | 2X",
        "type": "Vanilla",
        "connect": "connect monday.rustresort.com:28015",
        "store": "https://rustresort.com/store/3",
    },
    "thursday": {
        "label": "RustResort.com - EU Thursday | 2X",
        "type": "Vanilla",
        "connect": "connect thursday.rustresort.com:28015",
        "store": "https://rustresort.com/store/2",
    },
}


# ================== УТИЛИТЫ ==================
def load_cfg() -> dict:
    if not os.path.exists(CONFIG_PATH):
        save_cfg(DEFAULTS.copy())
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cfg(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def parse_hhmm(s: str) -> tuple[int, int]:
    try:
        h, m = s.strip().split(":")
        h, m = int(h), int(m)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h, m
    except Exception:
        return 17, 0  # безопасный дефолт


def combine_ts(date_: dt.date, hhmm: str) -> dt.datetime:
    h, m = parse_hhmm(hhmm)
    return dt.datetime(date_.year, date_.month, date_.day, h, m, tzinfo=TZ)


def unix_ts_from(dt_obj: dt.datetime) -> int:
    return int(dt_obj.timestamp())


def in_window(now: dt.datetime, target: dt.datetime, minutes: int) -> bool:
    return abs((now - target).total_seconds()) <= max(0, minutes) * 60


def tomorrow(date_: dt.date) -> dt.date:
    return date_ + dt.timedelta(days=1)


# ================== ТЕКСТЫ СООБЩЕНИЙ ==================
def msg_pre_anytime(day_key: str, wipe_no: int, ts_start: int) -> str:
    s = SERVERS[day_key]
    return (
        f"⏳ Менее чем через сутки стартует **{wipe_no}** вайп Деревни.\n"
        f"🕔 Старт: **<t:{ts_start}:R>**, <t:{ts_start}:f> *(по вашему времени)* ||@everyone||\n"
        f"🛰️ Сервер: **{s['label']}** (**{s['type']}**)\n\n"
        "🏕️ Зовите друзей, чтоб вступили в Деревню — играем по соседству. Дома, лут и пароли у каждого свои. Зелёнка общая.\n\n"
        "💰 Промо-код **VLG** даёт **+20%** при [донате.](" + s["store"] + ")"
    )


def msg_pre(day_key: str, wipe_no: int, ts_start: int) -> str:
    s = SERVERS[day_key]
    return (
        f"⏳ Менее чем через сутки стартует **{wipe_no}** вайп Деревни.\n"
        f"🕔 Старт: **<t:{ts_start}:R>**, <t:{ts_start}:f> *(по вашему времени)* ||@everyone||\n"
        f"🛰️ Сервер: **{s['label']}** (**{s['type']}**)\n\n"
        "🏕️ Зовите друзей, чтоб вступили в Деревню — играем по соседству. Дома, лут и пароли у каждого свои. Зелёнка общая.\n\n"
        "💰 Промо-код **VLG** даёт **+20%** при [донате.](" + s["store"] + ")"
    )


def msg_hour(day_key: str, wipe_no: int, ts_start: int) -> str:
    s = SERVERS[day_key]
    return (
        f"⌛ До старта **{wipe_no}** вайпа остаётся меньше **часа**: стартуем **<t:{ts_start}:R>**, в <t:{ts_start}:t> *(по вашему времени)* ||@everyone||\n"
        f"🌎 Server IP: ```{s['connect']}```"
    )


def msg_minute(ts_start: int) -> str:
    # без @everyone
    return f"⏱️ Сервер запускается <t:{ts_start}:R>, успейте вовремя скопировать и ввести **connect** сервера в окно консоля F1"


# ================== UI ПАНЕЛЬ ==================
class WipePanel(discord.ui.View):
    def __init__(self, bot: commands.Bot, cfg: dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.cfg = cfg

    def _embed(self) -> discord.Embed:
        ch = (
            f"<#{self.cfg['channel_id']}>"
            if self.cfg.get("channel_id")
            else "не выбран"
        )
        e = discord.Embed(title="Настройки автообъявлений вайпа", color=0x2B2D31)
        e.add_field(
            name="Статус",
            value=("Включено" if self.cfg["enabled"] else "Выключено"),
            inline=True,
        )
        e.add_field(name="Канал", value=ch, inline=True)
        e.add_field(
            name="Старт по Баку", value=self.cfg.get("start_time", "17:00"), inline=True
        )
        e.add_field(
            name="Следующий № вайпа", value=str(self.cfg.get("wipe_no", 0)), inline=True
        )
        e.add_field(
            name="Окно допуска, мин",
            value=str(self.cfg.get("window_minutes", 5)),
            inline=True,
        )
        e.add_field(
            name="Антидубли",
            value=f"T-24h: {self.cfg.get('last_pre_date','') or '—'} | "
            f"T-1h: {self.cfg.get('last_hour_date','') or '—'} | "
            f"T-1m: {self.cfg.get('last_minute_date','') or '—'}",
            inline=False,
        )
        e.set_footer(
            text="График: T-24h (вс/ср в start_time), T-1h (пн/чт за час), T-1m (пн/чт за минуту). Часовой пояс Asia/Baku."
        )
        return e

    @discord.ui.button(
        label="Вкл/Выкл", style=discord.ButtonStyle.green, custom_id="wipe_toggle"
    )
    async def btn_toggle(self, it: discord.Interaction, _: discord.ui.Button):
        self.cfg["enabled"] = not self.cfg.get("enabled", False)
        save_cfg(self.cfg)
        await it.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(
        label="Канал", style=discord.ButtonStyle.primary, custom_id="wipe_channel"
    )
    async def btn_channel(self, it: discord.Interaction, _: discord.ui.Button):
        await it.response.send_message(
            "Выберите канал:", view=ChannelPicker(self), ephemeral=True
        )

    @discord.ui.button(
        label="Старт HH:MM", style=discord.ButtonStyle.secondary, custom_id="wipe_time"
    )
    async def btn_time(self, it: discord.Interaction, _: discord.ui.Button):
        await it.response.send_modal(StartTimeModal(self))

    @discord.ui.button(
        label="Окно допуска",
        style=discord.ButtonStyle.secondary,
        custom_id="wipe_window",
    )
    async def btn_window(self, it: discord.Interaction, _: discord.ui.Button):
        await it.response.send_modal(WindowModal(self))

    @discord.ui.button(
        label="№ вайпа", style=discord.ButtonStyle.secondary, custom_id="wipe_wipeno"
    )
    async def btn_wipeno(self, it: discord.Interaction, _: discord.ui.Button):
        await it.response.send_modal(WipeNoModal(self))

    @discord.ui.button(
        label="Предпросмотр ПН (все)",
        style=discord.ButtonStyle.blurple,
        custom_id="wipe_preview_mon",
    )
    async def preview_mon(self, it: discord.Interaction, _: discord.ui.Button):
        now = dt.datetime.now(TZ)
        days_to_mon = (0 - now.weekday()) % 7
        mon_date = (now + dt.timedelta(days=days_to_mon)).date()
        if (
            days_to_mon == 0
            and now.time() > combine_ts(mon_date, self.cfg["start_time"]).time()
        ):
            mon_date += dt.timedelta(days=7)
        start_dt = combine_ts(mon_date, self.cfg["start_time"])
        msg = (
            ":small_blue_diamond: Завтра вайп Деревни VLG!\n"
            + msg_pre("monday", self.cfg["wipe_no"], unix_ts_from(start_dt))
            + "\n\n"
            + ":small_blue_diamond: Осталось менее часа до начала вайпа Деревни VLG!\n"
            + msg_hour("monday", self.cfg["wipe_no"], unix_ts_from(start_dt))
            + "\n\n"
            + ":small_blue_diamond: Пошёл отсчёт до старта вайпа...\n"
            + msg_minute(unix_ts_from(start_dt))
        )
        await it.response.send_message(msg, ephemeral=True)

    # ----- Принудительный PRE через кнопки -----
    @discord.ui.button(
        label="Force PRE ПН",
        style=discord.ButtonStyle.danger,
        custom_id="wipe_force_pre_mon",
    )
    async def force_pre_mon(self, it: discord.Interaction, _: discord.ui.Button):
        await self._force_pre("monday", it)

    @discord.ui.button(
        label="Force PRE ЧТ",
        style=discord.ButtonStyle.danger,
        custom_id="wipe_force_pre_thu",
    )
    async def force_pre_thu(self, it: discord.Interaction, _: discord.ui.Button):
        await self._force_pre("thursday", it)

    async def _force_pre(self, day_key: str, it: discord.Interaction):
        cfg = load_cfg()
        if not cfg.get("channel_id"):
            await it.response.send_message(
                "Сначала укажите канал: /wipe_channel", ephemeral=True
            )
            return

        now = dt.datetime.now(TZ)
        start_hhmm = cfg.get("start_time", "17:00")
        target_wd = 0 if day_key == "monday" else 3

        delta = (target_wd - now.weekday()) % 7
        target_date = (now + dt.timedelta(days=delta)).date()
        if delta == 0 and now.time() > combine_ts(target_date, start_hhmm).time():
            target_date += dt.timedelta(days=7)

        ts_start = unix_ts_from(combine_ts(target_date, start_hhmm))
        msg = msg_pre_anytime(day_key, cfg["wipe_no"], ts_start)

        ch = self.bot.get_channel(cfg["channel_id"])
        if isinstance(ch, discord.TextChannel):
            await ch.send(msg, allowed_mentions=discord.AllowedMentions(everyone=True))
            if now.date() == (target_date - dt.timedelta(days=1)):
                cfg["last_pre_date"] = now.date().isoformat()
                save_cfg(cfg)

        await it.response.send_message(
            "Принудительный PRE-анонс отправлен.", ephemeral=True
        )

    @discord.ui.button(
        label="Предпросмотр ЧТ (все)",
        style=discord.ButtonStyle.blurple,
        custom_id="wipe_preview_thu",
    )
    async def preview_thu(self, it: discord.Interaction, _: discord.ui.Button):
        now = dt.datetime.now(TZ)
        days_to_thu = (3 - now.weekday()) % 7
        thu_date = (now + dt.timedelta(days=days_to_thu)).date()
        if (
            days_to_thu == 0
            and now.time() > combine_ts(thu_date, self.cfg["start_time"]).time()
        ):
            thu_date += dt.timedelta(days=7)
        start_dt = combine_ts(thu_date, self.cfg["start_time"])
        msg = (
            ":small_orange_diamond: Завтра вайп Деревни VLG!\n"
            + msg_pre("thursday", self.cfg["wipe_no"], unix_ts_from(start_dt))
            + "\n\n"
            + ":small_orange_diamond: Уже через час вайп Деревни VLG!\n"
            + msg_hour("thursday", self.cfg["wipe_no"], unix_ts_from(start_dt))
            + "\n\n"
            + ":small_orange_diamond: Пошёл отсчёт до старта вайпа...\n"
            + msg_minute(unix_ts_from(start_dt))
        )
        await it.response.send_message(msg, ephemeral=True)


class ChannelPicker(discord.ui.View):
    def __init__(self, panel: WipePanel):
        super().__init__(timeout=120)
        self.panel = panel
        self.add_item(ChannelSelect(panel))


class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, panel: WipePanel):
        super().__init__(channel_types=[discord.ChannelType.text])
        self.panel = panel

    async def callback(self, it: discord.Interaction):
        ch = self.values[0]
        self.panel.cfg["channel_id"] = ch.id
        save_cfg(self.panel.cfg)
        await it.response.edit_message(
            content=f"Канал установлен: {ch.mention}", view=None
        )


class StartTimeModal(discord.ui.Modal, title="Время старта (по Баку)"):
    hhmm = discord.ui.TextInput(label="HH:MM", default="17:00", max_length=5)

    def __init__(self, panel: WipePanel):
        super().__init__()
        self.panel = panel
        self.hhmm.default = self.panel.cfg.get("start_time", "17:00")

    async def on_submit(self, it: discord.Interaction):
        self.panel.cfg["start_time"] = self.hhmm.value
        save_cfg(self.panel.cfg)
        await it.response.edit_message(embed=self.panel._embed(), view=self.panel)


class WindowModal(discord.ui.Modal, title="Окно допуска (мин)"):
    win = discord.ui.TextInput(
        label="± минут", default="5", max_length=3, required=True
    )

    def __init__(self, panel: WipePanel):
        super().__init__()
        self.panel = panel
        self.win.default = str(self.panel.cfg.get("window_minutes", 5))

    async def on_submit(self, it: discord.Interaction):
        try:
            self.panel.cfg["window_minutes"] = max(0, int(self.win.value))
        except Exception:
            self.panel.cfg["window_minutes"] = 5
        save_cfg(self.panel.cfg)
        await it.response.edit_message(embed=self.panel._embed(), view=self.panel)


class WipeNoModal(discord.ui.Modal, title="Следующий № вайпа"):
    num = discord.ui.TextInput(
        label="Число", default="192", max_length=6, required=True
    )

    def __init__(self, panel: WipePanel):
        super().__init__()
        self.panel = panel
        self.num.default = str(self.panel.cfg.get("wipe_no", 192))

    async def on_submit(self, it: discord.Interaction):
        try:
            self.panel.cfg["wipe_no"] = max(1, int(self.num.value))
        except Exception:
            pass
        save_cfg(self.panel.cfg)
        await it.response.edit_message(embed=self.panel._embed(), view=self.panel)


class BoostersPanel(discord.ui.View):
    def __init__(self, bot: commands.Bot, cfg: dict):
        super().__init__(timeout=300)
        self.bot, self.cfg = bot, cfg

    def _embed(self) -> discord.Embed:
        e = discord.Embed(title="Настройки благодарностей бустерам", color=0x2B2D31)
        ch = (
            f"<#{self.cfg.get('boosters_realtime_channel_id')}>"
            if self.cfg.get("boosters_realtime_channel_id")
            else "не выбран"
        )
        role = self.cfg.get("boosters_role_id") or "не задано"
        allowed = self.cfg.get("boosters_allowed_roles", [])
        allowed_fmt = ", ".join(f"<@&{rid}>" for rid in allowed) if allowed else "—"
        e.add_field(
            name="Реал-тайм спасибо",
            value=(
                "Включено" if self.cfg.get("boosters_realtime_enabled") else "Выключено"
            ),
            inline=True,
        )
        e.add_field(name="Канал для спасибо", value=ch, inline=True)
        e.add_field(name="Роль бустера (id)", value=str(role), inline=True)
        e.add_field(name="Разрешённые роли", value=allowed_fmt, inline=False)
        return e

    @discord.ui.button(
        label="Вкл/Выкл реал-тайм",
        style=discord.ButtonStyle.green,
        custom_id="boosters_toggle_rt",
    )
    async def toggle_rt(self, it: discord.Interaction, _: discord.ui.Button):
        self.cfg["boosters_realtime_enabled"] = not self.cfg.get(
            "boosters_realtime_enabled", False
        )
        save_cfg(self.cfg)
        await it.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(
        label="Канал спасибо",
        style=discord.ButtonStyle.primary,
        custom_id="boosters_pick_channel",
    )
    async def pick_channel(self, it: discord.Interaction, _: discord.ui.Button):
        await it.response.send_message(
            "Выберите канал:", view=BoostersChannelPicker(self), ephemeral=True
        )

    @discord.ui.button(
        label="Разрешённые роли",
        style=discord.ButtonStyle.secondary,
        custom_id="boosters_edit_allowed",
    )
    async def edit_allowed(self, it: discord.Interaction, _: discord.ui.Button):
        await it.response.send_modal(AllowedRolesModal(self))


class BoostersChannelPicker(discord.ui.View):
    def __init__(self, panel: BoostersPanel):
        super().__init__(timeout=120)
        self.add_item(BoostersChannelSelect(panel))


class BoostersChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, panel: BoostersPanel):
        super().__init__(channel_types=[discord.ChannelType.text])
        self.panel = panel

    async def callback(self, it: discord.Interaction):
        ch = self.values[0]
        self.panel.cfg["boosters_realtime_channel_id"] = ch.id
        save_cfg(self.panel.cfg)
        await it.response.edit_message(
            content=f"Канал для «спасибо» установлен: {ch.mention}", view=None
        )


class AllowedRolesModal(discord.ui.Modal, title="Разрешённые роли (ID через запятую)"):
    ids = discord.ui.TextInput(
        label="role_id,role_id,...", style=discord.TextStyle.paragraph, default=""
    )

    def __init__(self, panel: BoostersPanel):
        super().__init__()
        self.panel = panel
        cur = self.panel.cfg.get("boosters_allowed_roles", [])
        self.ids.default = ",".join(str(x) for x in cur) if cur else ""

    async def on_submit(self, it: discord.Interaction):
        raw = str(self.ids.value).strip()
        new_ids = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                try:
                    new_ids.append(int(part))
                except:
                    pass
        self.panel.cfg["boosters_allowed_roles"] = new_ids
        save_cfg(self.panel.cfg)
        await it.response.edit_message(embed=self.panel._embed(), view=self.panel)


# ================== ОСНОВНОЙ COG ==================
class WipeAnnounce(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ticker.start()
        self.boosters_ticker.start()

    def cog_unload(self):
        self.ticker.cancel()
        self.boosters_ticker.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        cfg = load_cfg()
        if cfg.get("panel_message_id") and cfg.get("panel_channel_id"):
            self.bot.add_view(
                WipePanel(self.bot, cfg), message_id=cfg["panel_message_id"]
            )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        cfg = load_cfg()
        if not cfg.get("boosters_realtime_enabled"):
            return
        ch_id = cfg.get("boosters_realtime_channel_id")
        role_id = cfg.get("boosters_role_id")
        allowed_ids = set(cfg.get("boosters_allowed_roles", []))
        if not ch_id or not role_id:
            return

        before_ids = {r.id for r in getattr(before, "roles", [])}
        after_ids = {r.id for r in getattr(after, "roles", [])}
        if role_id not in (after_ids - before_ids):
            return

        if after.bot or not any(r.id in allowed_ids for r in after.roles):
            return

        ch = self.bot.get_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            return

        try:
            await ch.send(
                f"Спасибо за поддержку Деревни! {after.mention}! Теперь Вы как Богач можете писать в <#{config.BOOSTERS_THANKS_CHANNEL_ID}> и через спец.раздел обращаться к 💜",
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False
                ),
            )
        except Exception as e:
            print(f"[boosters realtime] send failed: {e}")

    # ---- Панель и команды админа ----
    @commands.hybrid_command(
        name="wipe_panel", description="Панель автообъявлений вайпа"
    )
    @commands.has_permissions(administrator=True)
    async def wipe_panel(self, ctx: commands.Context):
        view = WipePanel(self.bot, load_cfg())
        msg = await ctx.reply(embed=view._embed(), view=view, mention_author=False)
        cfg = load_cfg()
        cfg["panel_message_id"] = msg.id
        cfg["panel_channel_id"] = msg.channel.id
        save_cfg(cfg)

    @commands.hybrid_command(
        name="wipe_enable", description="Включить/выключить автообъявления"
    )
    @commands.has_permissions(administrator=True)
    async def wipe_enable(self, ctx: commands.Context, on: bool):
        cfg = load_cfg()
        cfg["enabled"] = bool(on)
        save_cfg(cfg)
        await ctx.reply(
            f"Автообъявления: {'включены' if on else 'выключены'}", mention_author=False
        )

    @commands.hybrid_command(
        name="wipe_channel", description="Установить канал для объявлений"
    )
    @commands.has_permissions(administrator=True)
    async def wipe_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        cfg = load_cfg()
        cfg["channel_id"] = channel.id
        save_cfg(cfg)
        await ctx.reply(f"Канал установлен: {channel.mention}", mention_author=False)

    @commands.hybrid_command(
        name="wipe_reset_flags", description="Сброс антидублей за сегодня (для теста)"
    )
    @commands.has_permissions(administrator=True)
    async def wipe_reset_flags(self, ctx: commands.Context):
        cfg = load_cfg()
        for k in (
            "last_pre_date",
            "last_hour_date",
            "last_minute_date",
            "last_inc_date",
        ):
            cfg[k] = ""
        save_cfg(cfg)
        await ctx.reply(
            "Флаги T-24h / T-1h / T-1m и last_inc_date сброшены.", mention_author=False
        )

    @commands.hybrid_command(
        name="wipe_force_pre", description="Принудительно отправить PRE-анонс (Mon/Thu)"
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(day="День вайпа")
    @app_commands.choices(
        day=[
            app_commands.Choice(name="Понедельник", value="monday"),
            app_commands.Choice(name="Четверг", value="thursday"),
        ]
    )
    async def wipe_force_pre(self, ctx: commands.Context, day: str):
        cfg = load_cfg()
        if not cfg.get("channel_id"):
            await ctx.reply(
                "Сначала укажите канал: /wipe_channel", mention_author=False
            )
            return
        day_key = "monday" if day == "monday" else "thursday"

        now = dt.datetime.now(TZ)
        start_hhmm = cfg.get("start_time", "17:00")
        target_wd = 0 if day_key == "monday" else 3
        delta = (target_wd - now.weekday()) % 7
        target_date = (now + dt.timedelta(days=delta)).date()
        if delta == 0 and now.time() > combine_ts(target_date, start_hhmm).time():
            target_date += dt.timedelta(days=7)

        ts_start = unix_ts_from(combine_ts(target_date, start_hhmm))
        await self._send_text(
            cfg, msg_pre_anytime(day_key, cfg["wipe_no"], ts_start), ping_everyone=True
        )

        if now.date() == (target_date - dt.timedelta(days=1)):
            cfg["last_pre_date"] = now.date().isoformat()
            save_cfg(cfg)

        await ctx.reply(
            f"PRE отправлен для {'ПН' if day_key=='monday' else 'ЧТ'}.",
            mention_author=False,
        )

    @commands.hybrid_command(
        name="boosters_setup",
        description="Настроить канал и роль для благодарностей бустерам",
    )
    @commands.has_permissions(administrator=True)
    async def boosters_setup(
        self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role
    ):
        cfg = load_cfg()
        cfg["boosters_channel_id"] = channel.id
        cfg["boosters_role_id"] = role.id
        save_cfg(cfg)
        await ctx.reply(
            f"Ок! Канал: {channel.mention}, роль: {role.mention}", mention_author=False
        )

    @commands.hybrid_command(
        name="thank_boosters_now",
        description="Отправить благодарность бустерам прямо сейчас",
    )
    @commands.has_permissions(administrator=True)
    async def thank_boosters_now(self, ctx: commands.Context):
        await self._thank_boosters(check_monthly=False)
        await ctx.reply(
            "Отчёт о бустерах сервера (Богач) отправлен.", mention_author=False
        )

    @commands.hybrid_command(
        name="boosters_panel", description="Панель настроек благодарностей бустерам"
    )
    @commands.has_permissions(administrator=True)
    async def boosters_panel(self, ctx: commands.Context):
        view = BoostersPanel(self.bot, load_cfg())
        await ctx.reply(embed=view._embed(), view=view, mention_author=False)

    # ---- Планировщик ----
    @tasks.loop(seconds=20)
    async def ticker(self):
        cfg = load_cfg()
        if not cfg.get("enabled") or not cfg.get("channel_id"):
            return

        now = dt.datetime.now(TZ)
        today = now.date()
        wd = now.weekday()  # Mon=0 ... Sun=6
        start_hhmm = cfg.get("start_time", "17:00")
        start_dt_today = combine_ts(today, start_hhmm)
        start_dt_tomorrow = combine_ts(tomorrow(today), start_hhmm)
        win = cfg.get("window_minutes", 5)

        # T-24h: если завтра понедельник или четверг — сегодня в start_time публикуем анонс
        if tomorrow(today).weekday() in (0, 3):  # tomorrow is Mon or Thu
            if cfg.get("last_pre_date") != today.isoformat() and in_window(
                now, start_dt_today, win
            ):
                day_key = "monday" if tomorrow(today).weekday() == 0 else "thursday"
                ts_start = unix_ts_from(start_dt_tomorrow)
                await self._send_text(
                    cfg, msg_pre(day_key, cfg["wipe_no"], ts_start), ping_everyone=True
                )
                cfg["last_pre_date"] = today.isoformat()
                save_cfg(cfg)

        # T-1h: если сегодня понедельник или четверг — за час до старта
        if wd in (0, 3):
            hour_dt = start_dt_today - dt.timedelta(hours=1)
            if cfg.get("last_hour_date") != today.isoformat() and in_window(
                now, hour_dt, win
            ):
                day_key = "monday" if wd == 0 else "thursday"
                ts_start = unix_ts_from(start_dt_today)
                await self._send_text(
                    cfg, msg_hour(day_key, cfg["wipe_no"], ts_start), ping_everyone=True
                )
                cfg["last_hour_date"] = today.isoformat()
                save_cfg(cfg)

        # T-1m: за минуту до старта (без everyone) + инкремент номера
        if wd in (0, 3):
            minute_dt = start_dt_today - dt.timedelta(minutes=1)
            if cfg.get("last_minute_date") != today.isoformat() and in_window(
                now, minute_dt, win
            ):
                ts_start = unix_ts_from(start_dt_today)
                await self._send_text(cfg, msg_minute(ts_start), ping_everyone=False)
                cfg["last_minute_date"] = today.isoformat()
                # инкремент номера
                try:
                    cfg["wipe_no"] = int(cfg.get("wipe_no", 0)) + 1
                except Exception:
                    cfg["wipe_no"] = 1
                cfg["last_inc_date"] = today.isoformat()  # <-- здесь
                save_cfg(cfg)

        # Фолбэк: если 17:00 уже наступило, а T-1m не успели — всё равно увеличить номер один раз
        if (
            wd in (0, 3)
            and now >= start_dt_today
            and cfg.get("last_inc_date") != today.isoformat()
        ):
            if (
                cfg.get("last_minute_date") != today.isoformat()
            ):  # действительно пропустили T-1m
                try:
                    cfg["wipe_no"] = int(cfg.get("wipe_no", 0)) + 1
                except Exception:
                    cfg["wipe_no"] = 1
            cfg["last_inc_date"] = today.isoformat()  # <-- здесь инкремент
            save_cfg(cfg)

    @tasks.loop(hours=24)
    async def boosters_ticker(self):
        await self._thank_boosters(check_monthly=True)

    @boosters_ticker.before_loop
    async def before_boosters_ticker(self):
        await self.bot.wait_until_ready()

    @ticker.before_loop
    async def before_ticker(self):
        await self.bot.wait_until_ready()

    async def _thank_boosters(self, check_monthly: bool = False):
        try:
            cfg = load_cfg()

            # Проверяем настройки
            if not cfg.get("boosters_channel_id") or not cfg.get("boosters_role_id"):
                return

            channel = self.bot.get_channel(cfg["boosters_channel_id"])
            if not isinstance(channel, discord.TextChannel):
                return

            role = channel.guild.get_role(cfg["boosters_role_id"])
            if not role:
                return

            # Проверяем месяц
            now = dt.datetime.now(TZ)
            ym = now.strftime("%Y-%m")

            if check_monthly and cfg.get("last_thanks_ym") == ym:
                return

            # Получаем разрешенные роли из конфигурации
            allowed_ids = set(cfg.get("boosters_allowed_roles", []))

            # Получаем список бустеров с фильтрацией по разрешенным ролям
            boosters = [
                m
                for m in role.members
                if not m.bot and any(r.id in allowed_ids for r in m.roles)
            ]

            # Формируем сообщение
            if not boosters:
                message = f"В этом месяце нет бустеров роли {role.mention}"
            else:
                # Сортируем по display_name в алфавитном порядке
                boosters = sorted(
                    boosters, key=lambda m: (m.display_name or m.name).lower()
                )

                # Формируем заголовок с названием месяца
                month_names = {
                    "01": "Январь",
                    "02": "Февраль",
                    "03": "Март",
                    "04": "Апрель",
                    "05": "Май",
                    "06": "Июнь",
                    "07": "Июль",
                    "08": "Август",
                    "09": "Сентябрь",
                    "10": "Октябрь",
                    "11": "Ноябрь",
                    "12": "Декабрь",
                }
                month_name = month_names.get(now.strftime("%m"), now.strftime("%m"))
                year = now.strftime("%Y")

                header = f":purple_heart: За {month_name} {year} года благодарны Вам за поддержку Деревни бустом! Вы заслужили статус {role.mention}."

                # Формируем список бустеров
                booster_list = "\n".join([f"• {member.mention}" for member in boosters])

                message = f"{header}\n\n{booster_list}"

            # Отправляем сообщение
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions(
                    roles=True, users=True, everyone=False
                ),
            )

            # Обновляем конфиг при успехе
            cfg["last_thanks_ym"] = ym
            save_cfg(cfg)

        except Exception as e:
            print(f"[Boosters] Ошибка в _thank_boosters: {e}")

    async def _send_text(self, cfg: dict, content: str, ping_everyone: bool):
        ch = self.bot.get_channel(cfg["channel_id"])
        if not isinstance(ch, discord.TextChannel):
            return
        allowed = (
            discord.AllowedMentions(everyone=True)
            if ping_everyone
            else discord.AllowedMentions.none()
        )
        try:
            msg = await ch.send(content, allowed_mentions=allowed)

            # Если это сообщение без @everyone (T-1m), удаляем через 5 минут
            if not ping_everyone:
                import asyncio

                asyncio.create_task(self._auto_delete_message(msg))
        except Exception as e:
            print(f"[WipeAnnounce] send failed: {e}")

    async def _auto_delete_message(self, msg: discord.Message):
        try:
            import asyncio

            await asyncio.sleep(300)  # 5 минут
            await msg.delete()
        except Exception as e:
            print(f"[WipeAnnounce] auto delete failed: {e}")


# ================== SETUP ==================
async def setup(bot: commands.Bot):
    await bot.add_cog(WipeAnnounce(bot))
