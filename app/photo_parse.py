"""Чистые функции разбора текста, распознанного OCR на фото тренировки.

Ищет пары «значение + единица» для дистанции, скорости, пульса, набора
высоты, времени тренировки и даты. Двусмысленные или нераспознанные
значения не додумываются — остаются None.
"""
import re
from typing import Any, Dict, Optional

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
    text = text or ""
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

    confidence = round(len(fragments) / len(FIELDS), 2)

    return {**result, "confidence": confidence, "fragments": fragments}
