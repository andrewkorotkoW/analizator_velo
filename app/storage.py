import os
import sqlite3
from typing import List

from app.models import Workout

DB_PATH = os.environ.get(
    "ANAL_VELO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.db"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    date TEXT NOT NULL,
    distance_km REAL NOT NULL,
    duration_min REAL NOT NULL,
    avg_speed_kmh REAL,
    avg_hr REAL,
    elevation_gain_m REAL,
    source TEXT DEFAULT 'csv'
);
"""

# Дополнительные колонки для миграции уже существующих БД, созданных до их появления.
_MIGRATION_COLUMNS = {
    "source": "TEXT DEFAULT 'csv'",
    "elevation_gain_m": "REAL",
}

DUPLICATE_TOLERANCE = 0.01  # ±1% по дистанции считается той же тренировкой


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(_SCHEMA)
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(workouts)").fetchall()
        }
        for column, column_type in _MIGRATION_COLUMNS.items():
            if column not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE workouts ADD COLUMN {column} {column_type}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()
    finally:
        conn.close()


def _is_duplicate(known, date: str, distance_km: float) -> bool:
    for known_date, known_distance in known:
        if known_date != date:
            continue
        if known_distance == 0:
            if distance_km == 0:
                return True
            continue
        if abs(distance_km - known_distance) <= abs(known_distance) * DUPLICATE_TOLERANCE:
            return True
    return False


def save_workouts(user_email: str, workouts: List[Workout]) -> dict:
    """Сохраняет тренировки пользователя, пропуская дубли (та же дата и дистанция ±1%).

    Возвращает {"saved": <число сохранённых>, "duplicates": <число пропущенных дублей>}.
    """
    if not workouts:
        return {"saved": 0, "duplicates": 0}

    conn = get_connection()
    try:
        existing_rows = conn.execute(
            "SELECT date, distance_km FROM workouts WHERE user_email = ?",
            (user_email,),
        ).fetchall()
        known = [(row["date"], row["distance_km"]) for row in existing_rows]

        to_insert = []
        duplicates = 0
        for w in workouts:
            if _is_duplicate(known, w.date, w.distance_km):
                duplicates += 1
                continue
            known.append((w.date, w.distance_km))
            to_insert.append(w)

        if to_insert:
            conn.executemany(
                """
                INSERT INTO workouts
                    (user_email, date, distance_km, duration_min, avg_speed_kmh, avg_hr,
                     elevation_gain_m, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        user_email,
                        w.date,
                        w.distance_km,
                        w.duration_min,
                        w.avg_speed_kmh,
                        w.avg_hr,
                        w.elevation_gain_m,
                        w.source,
                    )
                    for w in to_insert
                ],
            )
            conn.commit()

        return {"saved": len(to_insert), "duplicates": duplicates}
    finally:
        conn.close()


def get_workouts(user_email: str) -> List[Workout]:
    """Возвращает тренировки пользователя, отсортированные по дате."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM workouts WHERE user_email = ? ORDER BY date ASC",
            (user_email,),
        ).fetchall()
        return [
            Workout(
                id=row["id"],
                user_email=row["user_email"],
                date=row["date"],
                distance_km=row["distance_km"],
                duration_min=row["duration_min"],
                avg_speed_kmh=row["avg_speed_kmh"],
                avg_hr=row["avg_hr"],
                elevation_gain_m=row["elevation_gain_m"],
                source=row["source"] or "csv",
            )
            for row in rows
        ]
    finally:
        conn.close()
