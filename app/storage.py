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
    avg_hr REAL
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_workouts(user_email: str, workouts: List[Workout]) -> int:
    """Сохраняет тренировки пользователя, возвращает число сохранённых строк."""
    if not workouts:
        return 0

    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO workouts
                (user_email, date, distance_km, duration_min, avg_speed_kmh, avg_hr)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_email,
                    w.date,
                    w.distance_km,
                    w.duration_min,
                    w.avg_speed_kmh,
                    w.avg_hr,
                )
                for w in workouts
            ],
        )
        conn.commit()
        return len(workouts)
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
            )
            for row in rows
        ]
    finally:
        conn.close()
