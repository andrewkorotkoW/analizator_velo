import os
import sqlite3
import uuid
from typing import List, Optional

from app.models import User, Workout

DB_PATH = os.environ.get(
    "ANAL_VELO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.db"),
)

TRACKS_DIR = os.environ.get(
    "ANAL_VELO_TRACKS_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace", "tracks"
    ),
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

_USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    age INTEGER,
    max_hr INTEGER,
    weight REAL
);
"""

# Дополнительные колонки для миграции уже существующих БД, созданных до их появления.
_MIGRATION_COLUMNS = {
    "source": "TEXT DEFAULT 'csv'",
    "elevation_gain_m": "REAL",
    "user_id": "INTEGER",
    "photo_path": "TEXT",
    "gpx_path": "TEXT",
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
        conn.execute(_USERS_SCHEMA)
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


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        name=row["name"],
        age=row["age"],
        max_hr=row["max_hr"],
        weight=row["weight"],
    )


def create_user(
    email: str,
    password_hash: str,
    name: Optional[str] = None,
    age: Optional[int] = None,
    max_hr: Optional[int] = None,
    weight: Optional[float] = None,
) -> User:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (email, password_hash, name, age, max_hr, weight)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (email, password_hash, name, age, max_hr, weight),
        )
        conn.commit()
        return User(
            id=cursor.lastrowid,
            email=email,
            password_hash=password_hash,
            name=name,
            age=age,
            max_hr=max_hr,
            weight=weight,
        )
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[User]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[User]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def update_user_profile(
    user_id: int,
    name: Optional[str] = None,
    age: Optional[int] = None,
    max_hr: Optional[int] = None,
    weight: Optional[float] = None,
) -> Optional[User]:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET name = ?, age = ?, max_hr = ?, weight = ? WHERE id = ?",
            (name, age, max_hr, weight, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_user_by_id(user_id)


def has_legacy_workouts(email: str) -> bool:
    """Есть ли тренировки с этим user_email, ещё не привязанные к аккаунту."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM workouts WHERE user_email = ? AND user_id IS NULL LIMIT 1",
            (email,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def migrate_email_to_user(email: str, user_id: int) -> int:
    """Привязывает существующие тренировки с этим user_email к аккаунту. Возвращает число строк."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE workouts SET user_id = ? WHERE user_email = ? AND user_id IS NULL",
            (user_id, email),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def save_gpx_track(user_id: int, content: bytes) -> str:
    """Сохраняет исходный GPX-файл на диск и возвращает путь для колонки gpx_path."""
    user_dir = os.path.join(TRACKS_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, f"{uuid.uuid4().hex}.gpx")
    with open(path, "wb") as f:
        f.write(content)
    return path


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


def save_workouts(user_email: str, workouts: List[Workout], user_id: Optional[int] = None) -> dict:
    """Сохраняет тренировки пользователя, пропуская дубли (та же дата и дистанция ±1%).

    Если передан user_id, дубли ищутся среди тренировок этого пользователя (по user_id);
    иначе — как раньше, по user_email (для обратной совместимости с данными без привязки).

    Возвращает {"saved": <число сохранённых>, "duplicates": <число пропущенных дублей>}.
    """
    if not workouts:
        return {"saved": 0, "duplicates": 0}

    conn = get_connection()
    try:
        if user_id is not None:
            existing_rows = conn.execute(
                "SELECT date, distance_km FROM workouts WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        else:
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
                    (user_email, user_id, date, distance_km, duration_min, avg_speed_kmh, avg_hr,
                     elevation_gain_m, source, photo_path, gpx_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        user_email,
                        user_id,
                        w.date,
                        w.distance_km,
                        w.duration_min,
                        w.avg_speed_kmh,
                        w.avg_hr,
                        w.elevation_gain_m,
                        w.source,
                        w.photo_path,
                        w.gpx_path,
                    )
                    for w in to_insert
                ],
            )
            conn.commit()

        return {"saved": len(to_insert), "duplicates": duplicates}
    finally:
        conn.close()


def get_workouts(user_email: Optional[str] = None, user_id: Optional[int] = None) -> List[Workout]:
    """Возвращает тренировки пользователя, отсортированные по дате.

    Если передан user_id, фильтрация идёт по нему; иначе — по user_email (обратная совместимость).
    """
    conn = get_connection()
    try:
        if user_id is not None:
            rows = conn.execute(
                "SELECT * FROM workouts WHERE user_id = ? ORDER BY date ASC",
                (user_id,),
            ).fetchall()
        else:
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
                photo_path=row["photo_path"],
                gpx_path=row["gpx_path"],
            )
            for row in rows
        ]
    finally:
        conn.close()


def delete_workout(user_id: int, workout_id: int) -> bool:
    """Удаляет тренировку, только если она принадлежит user_id. Возвращает True при удалении."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM workouts WHERE id = ? AND user_id = ?",
            (workout_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
