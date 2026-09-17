from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class User:
    """Зарегистрированный пользователь."""

    email: str
    password_hash: str
    name: Optional[str] = None
    age: Optional[int] = None
    max_hr: Optional[int] = None
    weight: Optional[float] = None
    id: Optional[int] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("password_hash", None)
        return data


@dataclass
class Workout:
    """Одна тренировка пользователя."""

    user_email: str
    date: str  # YYYY-MM-DD
    distance_km: float
    duration_min: float
    avg_speed_kmh: Optional[float] = None
    avg_hr: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    source: str = "csv"
    photo_path: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)
