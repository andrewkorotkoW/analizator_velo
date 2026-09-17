"""Чистые функции разбора текста, распознанного OCR на фото тренировки.

Ищет пары «значение + единица» для дистанции, скорости, пульса, набора
высоты, времени тренировки и даты. Двусмысленные или нераспознанные
значения не додумываются — остаются None.

На macOS без поддержки русского в Vision (см. app.ocr) кириллица иногда
всё равно распознаётся, но латинскими «двойниками» похожих по начертанию
букв и цифр (например, "PacctoAHMe" вместо "Расстояние", "KM/4" вместо
"км/ч" — "4" похожа на "ч"). normalize_transliteration() приводит такие
известные варианты к обычному виду перед разбором.
"""
import re
from typing import Any, Dict, List, Optional

FIELDS = [
    "date",
    "distance_km",
    "duration_min",
    "avg_speed_kmh",
    "avg_hr",
    "elevation_gain_m",
]

_DEC = r"\d+(?:[.,]\d+)?"

_SPEED_RE = re.compile(
    rf"(?P<value>{_DEC})\s*(?:км\s*/\s*ч|km\s*/\s*h)\b", re.IGNORECASE
)
_DISTANCE_RE = re.compile(
    rf"(?P<value>{_DEC})\s*(?:км|km)\b(?!\s*/\s*[чh])", re.IGNORECASE
)
_HR_RE = re.compile(
    rf"(?P<value>{_DEC})\s*(?:уд\s*/\s*мин|bpm|уд\.?\s*мин)\b", re.IGNORECASE
)
_ELEVATION_NUM_FIRST_RE = re.compile(
    rf"(?P<value>{_DEC})\s*(?:м|m)(?:\.)?\s*(?:набор[а-яё]*|подъ[её]м[а-яё]*|elev(?:ation)?)",
    re.IGNORECASE,
)
_ELEVATION_LABEL_FIRST_RE = re.compile(
    rf"(?:набор[а-яё]*\s+высот[а-яё]*|подъ[её]м[а-яё]*|elev(?:ation)?)\D{{0,12}}"
    rf"(?P<value>{_DEC})\s*(?:м|m)\b",
    re.IGNORECASE,
)
_DURATION_HMS_RE = re.compile(r"\b(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})\b")
_DURATION_WORDS_RE = re.compile(
    rf"(?:(?P<h>\d{{1,2}})\s*ч(?:ас(?:а|ов)?)?\.?\s*)?(?P<m>\d{{1,3}})\s*мин(?:ут[аы]?)?\.?(?!\w)",
    re.IGNORECASE,
)

_DATE_ISO_RE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
_DATE_DMY_RE = re.compile(r"\b(?P<d>\d{1,2})[./](?P<m>\d{1,2})[./](?P<y>\d{2,4})\b")
_DATE_WORDS_RE = re.compile(r"\b(?P<d>\d{1,2})\s+(?P<month>[А-Яа-яЁё]+)\s+(?P<y>\d{4})\b")

_MONTH_RU_PREFIX = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}

_MONTH_GENITIVE = {
    "янв": "января",
    "фев": "февраля",
    "мар": "марта",
    "апр": "апреля",
    "мая": "мая",
    "июн": "июня",
    "июл": "июля",
    "авг": "августа",
    "сен": "сентября",
    "окт": "октября",
    "ноя": "ноября",
    "дек": "декабря",
}

# =====================================================================
# Нормализация «латинских двойников» кириллицы (см. RUSSIAN_NOT_SUPPORTED_MESSAGE
# в app.ocr): на macOS < 13 Vision не поддерживает ru-RU, и русский текст на
# фото распознаётся похожими по начертанию латинскими буквами/цифрами —
# например, реальный вывод "PacctoAHMe / 42,3 KM / ... / 25,8 KM/4 / ... /
# 146 yA/MUH / Ha6op BbICoTbl / 410 M / 17 CeHTA6pa 2026".
# =====================================================================

# Известные соответствия букв в словах-«месяцах» их латинским/цифровым
# двойникам (по образцу "сентября" -> "CeHTA6pa": с/e/н/т/я/б/р/а совпадают
# по начертанию с c/e/H/T/A/6/p/a). Буквы без надёжного подтверждения
# (ф, и, ю, л, г, д и т.п.) не подменяются — распознаются только если OCR
# передал их правильно.
_MONTH_LOOKALIKE_LETTERS = {
    "а": "a", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "к": "k",
    "е": "e", "м": "m", "н": "h", "т": "t", "в": "b", "б": "6", "я": "a",
}


def _month_confusable_pattern(stem: str) -> str:
    parts = []
    for ch in stem:
        alt = _MONTH_LOOKALIKE_LETTERS.get(ch)
        parts.append(f"[{ch}{alt}]" if alt else re.escape(ch))
    return "".join(parts)


_MONTH_TRANSLIT_RES = [
    (
        re.compile(
            r"(?P<day>\b\d{1,2}\s+)" + _month_confusable_pattern(stem) + r"\w*(?P<year>\s+\d{4}\b)",
            re.IGNORECASE,
        ),
        genitive,
    )
    for stem, genitive in _MONTH_GENITIVE.items()
]


def _normalize_translit_months(text: str) -> str:
    for pattern, genitive in _MONTH_TRANSLIT_RES:
        text = pattern.sub(lambda m, g=genitive: f"{m.group('day')}{g}{m.group('year')}", text)
    return text


# Единицы: "4" вместо "ч" (км/4 -> км/ч), латинские "y"/"M"/"H" вместо
# "у"/"м"/"н" в "уд/мин" (yA/MUH, yд/мин -> bpm, уже понятный _HR_RE).
_KM_SLASH_4_RE = re.compile(r"\b(?:km|км)\s*/\s*4\b", re.IGNORECASE)
_HR_GARBLE_LATIN_RE = re.compile(r"\by[aд]\s*/\s*mu[hн]\b", re.IGNORECASE)
_HR_GARBLE_MIXED_RE = re.compile(r"\by\s*д\s*/\s*мин\b", re.IGNORECASE)

# Метки полей: известные латинские двойники конкретных русских слов.
_NABOR_RE = re.compile(r"\bha6op\b", re.IGNORECASE)
# "высоты" -> "BbICoTbl": Cyrillic "ы" часто распознаётся OCR как два
# латинских символа "bl"/"bI" (форма буквы похожа на "ь"+"I").
_VYSOTY_RE = re.compile(r"\bb[bl][il1]cot\w*\b", re.IGNORECASE)
_DISTANCE_LABEL_GARBLE_RE = re.compile(r"\bpacctoahme\b", re.IGNORECASE)
_SPEED_LABEL_GARBLE_RE = re.compile(r"\bckopoctb\b", re.IGNORECASE)
_PULSE_LABEL_GARBLE_RE = re.compile(r"\bnymbe\b", re.IGNORECASE)


def normalize_transliteration(text: str) -> str:
    """Приводит известные латинские «двойники» кириллицы к обычному виду.

    Применяется перед разбором, чтобы уже существующие регэкспы единиц/меток
    (_SPEED_RE, _HR_RE, _ELEVATION_*_RE, _DATE_WORDS_RE и т.д.) работали и на
    транслитерированном Vision-выводе без изменений."""
    text = _KM_SLASH_4_RE.sub("km/h", text)
    text = _HR_GARBLE_LATIN_RE.sub("bpm", text)
    text = _HR_GARBLE_MIXED_RE.sub("bpm", text)
    text = _NABOR_RE.sub("набор", text)
    text = _VYSOTY_RE.sub("высоты", text)
    text = _DISTANCE_LABEL_GARBLE_RE.sub("расстояние", text)
    text = _SPEED_LABEL_GARBLE_RE.sub("скорость", text)
    text = _PULSE_LABEL_GARBLE_RE.sub("пульс", text)
    text = _normalize_translit_months(text)
    return text


# =====================================================================
# Разбор «подпись на одной строке — значение на соседней» (типичная
# раскладка экранов велокомпьютеров), для случаев без единицы измерения
# рядом со значением. Если единица и число на одной строке — значение уже
# извлекается регэкспами выше и в фолбэк не попадает.
# =====================================================================

_BARE_NUMBER_RE = re.compile(rf"^(?P<value>{_DEC})")

_LABEL_PATTERNS: Dict[str, List[re.Pattern]] = {
    "distance_km": [re.compile(r"расстояни\w*|дистанци\w*|distance", re.IGNORECASE)],
    "avg_speed_kmh": [re.compile(r"скорост\w*|speed", re.IGNORECASE)],
    "avg_hr": [re.compile(r"пульс\w*|pulse|\bhr\b|heart\s*rate", re.IGNORECASE)],
    "elevation_gain_m": [
        re.compile(r"набор\s+высот\w*|подъ[её]м\w*|elev(?:ation)?(?:\s*gain)?", re.IGNORECASE)
    ],
}


def _apply_label_value_fallback(
    text: str, result: Dict[str, Optional[Any]], fragments: Dict[str, str]
) -> None:
    segments = [s.strip() for s in re.split(r"\n|\s/\s", text)]
    segments = [s for s in segments if s]

    for idx, segment in enumerate(segments):
        if any(ch.isdigit() for ch in segment):
            continue  # строка уже содержит число — не «чистая» подпись, не додумываем
        if idx + 1 >= len(segments):
            continue
        value_segment = segments[idx + 1]
        num_match = _BARE_NUMBER_RE.match(value_segment)
        if not num_match:
            continue

        for field, patterns in _LABEL_PATTERNS.items():
            if result.get(field) is not None:
                continue
            if any(p.search(segment) for p in patterns):
                result[field] = _to_float(num_match.group("value"))
                fragments[field] = f"{segment} → {value_segment}"
                break


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _valid_date(year: int, month: int, day: int) -> bool:
    if not (1 <= month <= 12):
        return False
    if not (1 <= day <= 31):
        return False
    if not (2000 <= year <= 2100):
        return False
    return True


def _normalize_year(year: int) -> int:
    if year < 100:
        return 2000 + year if year < 70 else 1900 + year
    return year


def _extract_date(text: str) -> tuple:
    """Возвращает (date_str, matched_fragment) или (None, None)."""
    m = _DATE_ISO_RE.search(text)
    if m:
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        if _valid_date(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}", m.group(0)

    m = _DATE_DMY_RE.search(text)
    if m:
        d, mo, y = int(m.group("d")), int(m.group("m")), _normalize_year(int(m.group("y")))
        if _valid_date(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}", m.group(0)

    m = _DATE_WORDS_RE.search(text)
    if m:
        stem = m.group("month").lower()[:3]
        mo = _MONTH_RU_PREFIX.get(stem)
        if mo is not None:
            d, y = int(m.group("d")), int(m.group("y"))
            if _valid_date(y, mo, d):
                return f"{y:04d}-{mo:02d}-{d:02d}", m.group(0)

    return None, None


def _extract_duration_min(text: str) -> tuple:
    m = _DURATION_HMS_RE.search(text)
    if m:
        h, mi, s = int(m.group("h")), int(m.group("m")), int(m.group("s"))
        return h * 60 + mi + s / 60.0, m.group(0)

    m = _DURATION_WORDS_RE.search(text)
    if m:
        h = int(m.group("h")) if m.group("h") else 0
        mi = int(m.group("m"))
        return float(h * 60 + mi), m.group(0)

    return None, None


def parse_ocr_text(text: str) -> Dict[str, Any]:
    """Разбирает текст OCR на поля тренировки.

    Возвращает словарь с ключами из FIELDS (значение или None), плюс
    "confidence" (доля распознанных полей) и "fragments" (сырые куски
    текста, из которых извлечено каждое значение).
    """
    text = normalize_transliteration(text or "")
    result: Dict[str, Optional[Any]] = {field: None for field in FIELDS}
    fragments: Dict[str, str] = {}

    m = _SPEED_RE.search(text)
    if m:
        result["avg_speed_kmh"] = _to_float(m.group("value"))
        fragments["avg_speed_kmh"] = m.group(0).strip()

    m = _DISTANCE_RE.search(text)
    if m:
        result["distance_km"] = _to_float(m.group("value"))
        fragments["distance_km"] = m.group(0).strip()

    m = _HR_RE.search(text)
    if m:
        result["avg_hr"] = _to_float(m.group("value"))
        fragments["avg_hr"] = m.group(0).strip()

    m = _ELEVATION_NUM_FIRST_RE.search(text) or _ELEVATION_LABEL_FIRST_RE.search(text)
    if m:
        result["elevation_gain_m"] = _to_float(m.group("value"))
        fragments["elevation_gain_m"] = m.group(0).strip()

    duration_min, duration_fragment = _extract_duration_min(text)
    if duration_min is not None:
        result["duration_min"] = duration_min
        fragments["duration_min"] = duration_fragment.strip()

    date_str, date_fragment = _extract_date(text)
    if date_str is not None:
        result["date"] = date_str
        fragments["date"] = date_fragment.strip()

    _apply_label_value_fallback(text, result, fragments)

    confidence = round(len(fragments) / len(FIELDS), 2)

    return {**result, "confidence": confidence, "fragments": fragments}
