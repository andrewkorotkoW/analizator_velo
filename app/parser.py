import csv
import io
import math
import os
from typing import List, Optional

import fitparse
import gpxpy

from app.models import Workout

REQUIRED_COLUMNS = ["date", "distance_km", "duration_min"]
OPTIONAL_COLUMNS = ["avg_speed_kmh", "avg_hr"]

MOVING_GAP_THRESHOLD_S = 30
ELEVATION_SMOOTHING_WINDOW = 3
EARTH_RADIUS_KM = 6371.0088


class ParseError(ValueError):
    """Общая ошибка разбора файла с тренировками (CSV/GPX/FIT)."""


class CsvParseError(ParseError):
    """Ошибка разбора CSV с тренировками."""


class GpxParseError(ParseError):
    """Ошибка разбора GPX-трека."""


class FitParseError(ParseError):
    """Ошибка разбора FIT-файла."""


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
                source="csv",
            )
        )

    if not workouts:
        raise CsvParseError("CSV не содержит ни одной строки с данными")

    return workouts


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def _moving_average(values: List[float], window: int) -> List[float]:
    n = len(values)
    half = window // 2
    result = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        chunk = values[lo:hi]
        result.append(sum(chunk) / len(chunk))
    return result


def _elevation_gain(elevations: List[float]) -> Optional[float]:
    if len(elevations) < 2:
        return None
    values = elevations
    if len(elevations) >= ELEVATION_SMOOTHING_WINDOW:
        values = _moving_average(elevations, ELEVATION_SMOOTHING_WINDOW)
    gain = 0.0
    for prev, cur in zip(values, values[1:]):
        if cur > prev:
            gain += cur - prev
    return gain


GARMIN_TPE_HR_SUFFIX = "}hr"


def _find_hr_in_element(element) -> Optional[float]:
    tag = element.tag
    if tag == "hr" or tag.endswith(GARMIN_TPE_HR_SUFFIX):
        try:
            return float(element.text)
        except (TypeError, ValueError):
            return None
    for child in element:
        hr = _find_hr_in_element(child)
        if hr is not None:
            return hr
    return None


def _extract_gpx_hr(point) -> Optional[float]:
    for ext in point.extensions:
        hr = _find_hr_in_element(ext)
        if hr is not None:
            return hr
    return None


def parse_gpx(content: bytes, user_email: str) -> List[Workout]:
    """Парсит GPX-трек в одну тренировку.

    Дистанция — сумма гаверсинусов между соседними точками с временем.
    Время в движении исключает паузы дольше 30 секунд и используется для
    расчёта средней скорости. Набор высоты считается по приростам после
    сглаживания скользящим средним (окно 3), чтобы игнорировать шум GPS.
    """
    try:
        gpx = gpxpy.parse(io.BytesIO(content))
    except Exception as exc:
        raise GpxParseError(f"Не удалось разобрать GPX-файл: {exc}")

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            points.extend(segment.points)

    timed_points = [p for p in points if p.time is not None]
    if len(timed_points) < 2:
        raise GpxParseError(
            "В GPX-треке нет точек с временем или их меньше двух — невозможно посчитать тренировку"
        )

    distance_km = 0.0
    moving_seconds = 0.0
    for a, b in zip(timed_points, timed_points[1:]):
        distance_km += _haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
        dt = (b.time - a.time).total_seconds()
        if dt <= MOVING_GAP_THRESHOLD_S:
            moving_seconds += dt

    start_time = timed_points[0].time
    end_time = timed_points[-1].time
    duration_min = (end_time - start_time).total_seconds() / 60.0

    avg_speed_kmh = distance_km / (moving_seconds / 3600.0) if moving_seconds > 0 else None

    elevations = [p.elevation for p in timed_points if p.elevation is not None]
    ascent = _elevation_gain(elevations)

    hr_values = [hr for hr in (_extract_gpx_hr(p) for p in timed_points) if hr is not None]
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else None

    date = start_time.strftime("%Y-%m-%d")

    return [
        Workout(
            user_email=user_email,
            date=date,
            distance_km=distance_km,
            duration_min=duration_min,
            avg_speed_kmh=avg_speed_kmh,
            avg_hr=avg_hr,
            elevation_gain_m=ascent,
            source="gpx",
        )
    ]


def _semicircles_to_degrees(value: int) -> float:
    return value * (180.0 / 2 ** 31)


def _workout_from_fit_session(msg, user_email: str) -> Workout:
    total_distance_m = msg.get_value("total_distance")
    total_timer_time_s = msg.get_value("total_timer_time")
    if total_distance_m is None or total_timer_time_s is None:
        raise FitParseError(
            "В FIT session-сообщении отсутствуют total_distance или total_timer_time"
        )

    start_time = msg.get_value("start_time")
    if start_time is None:
        raise FitParseError("В FIT session-сообщении отсутствует start_time")

    distance_km = total_distance_m / 1000.0
    duration_min = total_timer_time_s / 60.0

    avg_speed_mps = msg.get_value("avg_speed")
    if avg_speed_mps is not None:
        avg_speed_kmh = avg_speed_mps * 3.6
    elif total_timer_time_s > 0:
        avg_speed_kmh = distance_km / (total_timer_time_s / 3600.0)
    else:
        avg_speed_kmh = None

    return Workout(
        user_email=user_email,
        date=start_time.strftime("%Y-%m-%d"),
        distance_km=distance_km,
        duration_min=duration_min,
        avg_speed_kmh=avg_speed_kmh,
        avg_hr=msg.get_value("avg_heart_rate"),
        elevation_gain_m=msg.get_value("total_ascent"),
        source="fit",
    )


def _workout_from_fit_records(records, user_email: str) -> Workout:
    timestamps = []
    distances = []
    positions = []
    hr_values = []
    altitudes = []

    for rec in records:
        ts = rec.get_value("timestamp")
        if ts is not None:
            timestamps.append(ts)

        dist = rec.get_value("distance")
        if dist is not None:
            distances.append(dist)

        lat = rec.get_value("position_lat")
        lon = rec.get_value("position_long")
        if lat is not None and lon is not None:
            positions.append((_semicircles_to_degrees(lat), _semicircles_to_degrees(lon)))

        hr = rec.get_value("heart_rate")
        if hr is not None:
            hr_values.append(hr)

        alt = rec.get_value("altitude")
        if alt is None:
            alt = rec.get_value("enhanced_altitude")
        if alt is not None:
            altitudes.append(alt)

    if not timestamps:
        raise FitParseError("FIT record-сообщения не содержат timestamp")

    if distances:
        distance_km = distances[-1] / 1000.0
    elif len(positions) >= 2:
        distance_km = sum(
            _haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(positions, positions[1:])
        )
    else:
        raise FitParseError("Невозможно определить дистанцию: нет ни distance, ни координат")

    start_time = min(timestamps)
    end_time = max(timestamps)
    duration_min = (end_time - start_time).total_seconds() / 60.0
    avg_speed_kmh = distance_km / (duration_min / 60.0) if duration_min > 0 else None
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else None
    ascent = _elevation_gain_raw(altitudes)

    return Workout(
        user_email=user_email,
        date=start_time.strftime("%Y-%m-%d"),
        distance_km=distance_km,
        duration_min=duration_min,
        avg_speed_kmh=avg_speed_kmh,
        avg_hr=avg_hr,
        elevation_gain_m=ascent,
        source="fit",
    )


def _elevation_gain_raw(altitudes: List[float]) -> Optional[float]:
    if len(altitudes) < 2:
        return None
    gain = 0.0
    for prev, cur in zip(altitudes, altitudes[1:]):
        if cur > prev:
            gain += cur - prev
    return gain


def parse_fit(content: bytes, user_email: str) -> List[Workout]:
    """Парсит FIT-файл. Берёт session, а если его нет — агрегирует record-сообщения."""
    try:
        fit_file = fitparse.FitFile(io.BytesIO(content))
        messages = list(fit_file.get_messages())
    except Exception as exc:
        raise FitParseError(f"Не удалось разобрать FIT-файл: {exc}")

    session_messages = [m for m in messages if m.name == "session"]
    if session_messages:
        return [_workout_from_fit_session(session_messages[0], user_email)]

    record_messages = [m for m in messages if m.name == "record"]
    if not record_messages:
        raise FitParseError("FIT-файл не содержит данных о тренировке (нет session/record)")

    return [_workout_from_fit_records(record_messages, user_email)]


def detect_file_type(filename: str, content: bytes) -> str:
    """Определяет тип файла (csv/gpx/fit) по расширению, с фолбэком на сниффинг содержимого."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in (".csv", ".gpx", ".fit"):
        return ext[1:]

    head = content.lstrip()[:64]
    if head.startswith(b"<?xml") or head.startswith(b"<gpx"):
        return "gpx"
    if len(content) >= 12 and content[8:12] == b".FIT":
        return "fit"
    return "csv"


def parse_file(filename: str, content: bytes, user_email: str) -> List[Workout]:
    """Диспетчер: определяет тип файла и вызывает соответствующий парсер."""
    file_type = detect_file_type(filename, content)

    if file_type == "gpx":
        return parse_gpx(content, user_email)
    if file_type == "fit":
        return parse_fit(content, user_email)

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvParseError("Файл должен быть в кодировке UTF-8") from exc
    return parse_csv(text, user_email)
