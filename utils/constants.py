"""Константы для валидации и фильтрации"""

import re

# Паттерн для запрещённых символов
FORBIDDEN_SYMBOLS_PATTERN = re.compile(r"[卍☬♛♚☠︎★☆彡✿✧•◇◆❖¤۞۩⛧⛥⚔️🔞🚫📛👿👺👹]")

# Список запрещённых слов (мат и неприемлемые выражения)
BANNED_WORDS = [
    # Прямой мат кириллицей
    "хуй",
    "хуи",
    "хую",
    "хуя",
    "хуе",
    "хуём",
    "хуем",
    "хуйня",
    "ебать",
    "ебашь",
    "ебашу",
    "ебашит",
    "еблан",
    "ебучий",
    "ебучка",
    "ебало",
    "ебальник",
    "пизда",
    "пиздец",
    "пиздеж",
    "пиздюк",
    "пиздюля",
    "блядь",
    "блять",
    "блядина",
    "блядский",
    "говно",
    "говнюк",
    "говнюха",
    "говнища",
    "сука",
    "сучка",
    "сучий",
    "сученыш",
    "залупа",
    "жопа",
    "жопный",
    "жопник",
    "гандон",
    "пидор",
    "пидорас",
    "пидарас",
    "мудак",
    "мудила",
    "мудня",
    # Латинские транслитерации
    "khui",
    "hui",
    "huy",
    "huй",
    "хyй",
    "хyи",
    "ebashy",
    "ebash",
    "ebashu",
    "ebat",
    "ebaty",
    "eban",
    "ebalo",
    "ebalnik",
    "pizda",
    "pizdets",
    "pizdezh",
    "pizdyuk",
    "pizdulya",
    "blyad",
    "blyat",
    "blyady",
    "blyadina",
    "blyadskiy",
    "govno",
    "govnyuk",
    "govnyuha",
    "govnishcha",
    "suka",
    "suchka",
    "suchiy",
    "suchenysh",
    "zalupa",
    "zhopa",
    "zhopnyy",
    "zhopnik",
    "gandon",
    "pidor",
    "pidoras",
    "pidaras",
    "mudak",
    "mudila",
    "mudnya",
    # Английский мат
    "fuck",
    "shit",
    "bitch",
    "asshole",
    "cunt",
    "whore",
    "motherfucker",
    "bastard",
    "dickhead",
    # Другие неприемлемые слова
    "долбоеб",
    "debil",
    "retard",
    "гамноед",
]

# Минимальный возраст аккаунта в днях
MIN_ACCOUNT_AGE_DAYS = 2

# Поддельные домены Steam
FAKE_STEAM_DOMAINS = [
    "xn--steamcommunity-vul.com",
    "steamcommunlty.com",
    "steamcommunitty.com",
    "steamcommunity.ru",
    "steamcommunity.org",
]

# Разрешённые роли для команд
ALLOWED_ROLES = ["Житель", "Гражданин"]

# Роли модераторов
MODERATOR_ROLES = ["Ополчение", "Житель", "Гражданин"]

# Роли администраторов
ADMIN_ROLES = ["Администратор", "Офицер", "Гражданин", "Житель"]

# Rust App ID в Steam
RUST_APP_ID = 252490

# Регулярные выражения
STEAM_URL_PATTERN = r"https?://(?:www\.)?steamcommunity\.com/(?:id|profiles)/[\w-]+"
STEAM_ID_PATTERN = r"\b(765611\d{11})\b"
DISCORD_ID_PATTERN = r"(\d{17,20})"

# Символы для проверки никнеймов
# FORBIDDEN_SYMBOLS_PATTERN = r"[卍☬♛♚☠︎★☆彡✿✧•◇◆❖¤۞۩⛧⛥⚔️🔞🚫📛👿👺👹]" # Replaced by regex object above

# Списки запрещённых слов
# BANNED_WORDS = [ # Replaced by list above
#    # Прямой мат кириллицей (ПОЛНЫЕ СЛОВА)
#    "хуй", "хуи", "хую", "хуя", "хуе", "хуём", "хуем", "хуйня",
#    "ебать", "ебашь", "ебашу", "ебашит", "еблан", "ебучий", "ебучка", "ебало", "ебальник",
#    "пизда", "пиздец", "пиздеж", "пиздюк", "пиздюля",
#    "блядь", "блять", "блядина", "блядский",
#    "говно", "говнюк", "говнюха", "говнища",
#    "сука", "сучка", "сучий", "сученыш",
#    "залупа", "жопа", "жопный", "жопник",
#    "гандон", "пидор", "пидорас", "пидарас",
#    "мудак", "мудила", "мудня",
#
#    # Латинские транслитерации ПОЛНОГО мата (точные совпадения)
#    "khui", "hui", "huy", "huй", "хyй", "хyи",
#    "ebashy", "ebash", "ebashu", "ebat", "ebaty", "eban", "ebalo", "ebalnik",
#    "pizda", "pizdets", "pizdezh", "pizdyuk", "pizdulya",
#    "blyad", "blyat", "blyady", "blyadina", "blyadskiy",
#    "govno", "govnyuk", "govnyuha", "govnishcha",
#    "suka", "suchka", "suchiy", "suchenysh",
#    "zalupa", "zhopa", "zhopnyy", "zhopnik",
#    "gandon", "pidor", "pidoras", "pidaras",
#    "mudak", "mudila", "mudnya",
#
#    # Смешанные варианты (кириллица + латиница)
#    "пизd", "бляd", "ебаshy", "ебаsh", "мудаk", "сукa", "жоpa", "говнo",
#
#    # Цифровые замены
#    "ху1", "х1й", "п1здец", "бл1дь", "е6ашу", "е6аш",
#    "м0дак", "с0ка", "п0дор", "г0вно", "3алупа", "ж0па", "ж0пник",
#
#    # Английский мат (ТОЛЬКО откровенный)
#    "fuck", "shit", "bitch", "asshole", "cunt", "whore", "motherfucker", "bastard", "dickhead",
#    "dick", "cock", "penis", "pussy", "vagina", "faggot", "fag", "retard",
#
#    # Расистские и дискриминационные термины
#    "nigga", "nigger", "n1gga", "n1gger", "niga", "niger", "nіgga", "nіgger",
#    "nazi", "hitler", "jew", "kike", "chink", "gook", "spic", "wetback",
#    "negr", "cherniy", "chornyy", "zhid", "khach", "churka", "azer", "armyash",
#    "хач", "черномазый", "негр", "жид", "армяш", "азер", "чурка",
#
#    # Другие неприемлемые слова (ТОЛЬКО ПОЛНЫЕ СОВПАДЕНИЯ)
#    "долбоеб", "debil", "гамноед", "gay", "homo", "queer", "dyke", "tranny"
# ]

# Шаблоны для проверки качества ответов
JUNK_PATTERNS = [
    r"^\d+$",  # только цифры
    r"^[qwerty]+$",  # набор qwerty
    r"^[asdf]+$",  # набор asdf
    r"^[a-z]{1,3}$",  # короткие наборы букв
    r"^\W+$",  # только символы
    r"^(нет|нету|не знаю|-)$",  # отказы
    r"^(да|нет|\+|-)$",  # односложные ответы
    r"^[а-я]{1,3}$",  # короткие русские слова
    r"^(хз|пох|норм|ок|окей)$",  # сленговые сокращения
    r"^[0-9a-f]{6,}$",  # hex-коды
    r"^[xyz]+$",  # повторы букв
    r"^test$|^тест$",  # тестовые значения
    r"^(asdasd|qweqwe|123123|abc)$",  # мусорные комбинации
]

# Паттерны для уточнения
CLARIFICATION_PATTERNS = [r"друг", r"мой друг", r"знакомый", r"товарищ"]

# Серверы Rust Resort
RUST_SERVERS = {
    "monday": "connect monday.rustresort.com:28015",
    "thursday": "connect thursday.rustresort.com:28015",
    "friday": "connect friday.rustresort.com:28015",
}
# """Константы для валидации данных""" # Redundant header

# Паттерны для валидации
# STEAM_URL_PATTERN = r'https?://steamcommunity\.com/(?:id/[^/\s]+|profiles/\d+)/?' # Redundant
STEAM_ID_PATTERN = r"\b7656119\d{10}\b"  # SteamID64 формат
DISCORD_ID_PATTERN = r"<@!?(\d{17,19})>"  # Discord упоминания

# Запрещенные символы в никах
# FORBIDDEN_SYMBOLS_PATTERN = r'[☬☠♛卍༒︎Ƚ︎ÙçҜყ︎Δ]' # Redundant

# Запрещенные слова
# BANNED_WORDS = [ # Redundant
#    # Прямой мат кириллицей (ПОЛНЫЕ СЛОВА)
#    "хуй", "хуи", "хую", "хуя", "хуе", "хуём", "хуем", "хуйня",
#    "ебать", "ебашь", "ебашу", "ебашит", "еблан", "ебучий", "ебучка", "ебало", "ебальник",
#    "пизда", "пиздец", "пиздеж", "пиздюк", "пиздюля",
#    "блядь", "блять", "блядина", "блядский",
#    "говно", "говнюк", "говнюха", "говнища",
#    "сука", "сучка", "сучий", "сученыш",
#    "залупа", "жопа", "жопный", "жопник",
#    "гандон", "пидор", "пидорас", "пидарас",
#    "мудак", "мудила", "мудня",
#
#    # Латинские транслитерации ПОЛНОГО мата (точные совпадения)
#    "khui", "hui", "huy", "huй", "хyй", "хyи",
#    "ebashy", "ebash", "ebashu", "ebat", "ebaty", "eban", "ebalo", "ebalnik",
#    "pizda", "pizdets", "pizdezh", "pizdyuk", "pizdulya",
#    "blyad", "blyat", "blyady", "blyadina", "blyadskiy",
#    "govno", "govnyuk", "govnyuha", "govnishcha",
#    "suka", "suchka", "suchiy", "suchenysh",
#    "zalupa", "zhopa", "zhopnyy", "zhopnik",
#    "gandon", "pidor", "pidoras", "pidaras",
#    "mudak", "mudila", "mudnya",
#
#    # Смешанные варианты (кириллица + латиница)
#    "пизd", "бляd", "ебаshy", "ебаsh", "мудаk", "сукa", "жоpa", "говнo",
#
#    # Цифровые замены
#    "ху1", "х1й", "п1здец", "бл1дь", "е6ашу", "е6аш",
#    "м0дак", "с0ка", "п0дор", "г0вно", "3алупа", "ж0па", "ж0пник",
#
#    # Английский мат (ТОЛЬКО откровенный)
#    "fuck", "shit", "bitch", "asshole", "cunt", "whore", "motherfucker", "bastard", "dickhead",
#    "dick", "cock", "penis", "pussy", "vagina", "faggot", "fag", "retard",
#
#    # Расистские и дискриминационные термины
#    "nigga", "nigger", "n1gga", "n1gger", "niga", "niger", "nіgga", "nіgger",
#    "nazi", "hitler", "jew", "kike", "chink", "gook", "spic", "wetback",
#    "negr", "cherniy", "chornyy", "zhid", "khach", "churka", "azer", "armyash",
#    "хач", "черномазый", "негр", "жид", "армяш", "азер", "чурка",
#
#    # Другие неприемлемые слова (ТОЛЬКО ПОЛНЫЕ СОВПАДЕНИЯ)
#    "долбоеб", "debil", "гамноед", "gay", "homo", "queer", "dyke", "tranny"
# ]

# Мусорные паттерны
JUNK_PATTERNS = [
    r"^\d+$",  # только цифры
    r"^[qwerty]+$",  # набор qwerty
    r"^[asdf]+$",  # набор asdf
    r"^[a-z]{1,3}$",  # короткие наборы букв
    r"^\W+$",  # только символы
    r"^(нет|нету|не знаю|-)$",  # отказы
    r"^(да|нет|\+|-)$",  # односложные ответы
    r"^[а-я]{1,3}$",  # короткие русские слова
    r"^(хз|пох|норм|ок|окей)$",  # сленговые сокращения
]

# Список подозрительных паттернов для никнеймов
SUSPICIOUS_NICKNAME_PATTERNS = [
    r"^\d+$",  # только цифры
    r"^[qwerty]+$",  # набор qwerty
    r"^[asdf]+$",  # набор asdf
    r"^[a-z]{1,3}$",  # короткие наборы букв
    r"^\W+$",  # только символы
    r"^(test|тест)$",  # тестовые ники
]
