from dataclasses import dataclass, asdict
from typing import Optional


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
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)
