import csv
import io
from typing import List

from app.models import Workout

REQUIRED_COLUMNS = ["date", "distance_km", "duration_min"]
OPTIONAL_COLUMNS = ["avg_speed_kmh", "avg_hr"]


class CsvParseError(ValueError):
    """Ошибка разбора CSV с тренировками."""


def _parse_float(value: str, column: str, row_num: int) -> float:
    value = (value or "").strip()
    try:
        return float(value)
    except ValueError:
        raise CsvParseError(
            f"Строка {row_num}: некорректное значение '{value}' в колонке '{column}'"
        )


def _parse_optional_float(value, column: str, row_num: int):
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    return _parse_float(value, column, row_num)


def parse_csv(file_content: str, user_email: str) -> List[Workout]:
    """Парсит CSV-текст с колонками date,distance_km,duration_min,avg_speed_kmh,avg_hr.

    avg_speed_kmh и avg_hr опциональны. Бросает CsvParseError при отсутствии
    обязательных колонок или некорректных значениях.
    """
    reader = csv.DictReader(io.StringIO(file_content))

    if reader.fieldnames is None:
        raise CsvParseError("Пустой CSV-файл")

    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise CsvParseError(f"В CSV отсутствуют обязательные колонки: {', '.join(missing)}")

    workouts: List[Workout] = []
    for row_num, row in enumerate(reader, start=2):  # строка 1 — заголовок
        date = (row.get("date") or "").strip()
        if not date:
            raise CsvParseError(f"Строка {row_num}: отсутствует дата")

        distance_km = _parse_float(row.get("distance_km"), "distance_km", row_num)
        duration_min = _parse_float(row.get("duration_min"), "duration_min", row_num)
        avg_speed_kmh = _parse_optional_float(
            row.get("avg_speed_kmh"), "avg_speed_kmh", row_num
        )
        avg_hr = _parse_optional_float(row.get("avg_hr"), "avg_hr", row_num)

        workouts.append(
            Workout(
                user_email=user_email,
                date=date,
                distance_km=distance_km,
                duration_min=duration_min,
                avg_speed_kmh=avg_speed_kmh,
                avg_hr=avg_hr,
            )
        )

    if not workouts:
        raise CsvParseError("CSV не содержит ни одной строки с данными")

    return workouts
