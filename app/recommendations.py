from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from app.models import Workout

MIN_WORKOUTS = 4
CHANGE_THRESHOLD = 0.05
DEFAULT_MAX_HR = 190
WEEKLY_GROWTH_WARNING_PCT = 10.0
OVERTRAINING_STREAK = 3
OVERTRAINING_SPEED_TOLERANCE = 0.05
NO_REST_STREAK_DAYS = 5
LONG_PAUSE_DAYS = 7

# (имя зоны, нижняя граница, верхняя граница) в долях от max_hr
HR_ZONES = (
    ("Z1", 0.50, 0.60),
    ("Z2", 0.60, 0.70),
    ("Z3", 0.70, 0.80),
    ("Z4", 0.80, 0.90),
    ("Z5", 0.90, None),
)


def _avg(values: List[float]) -> float:
    return sum(values) / len(values)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def resolve_max_hr(user_max_hr: Optional[int] = None, age: Optional[int] = None) -> int:
    """Максимальный пульс: заданный вручную, иначе по возрасту (220-возраст), иначе дефолт."""
    if user_max_hr is not None:
        return user_max_hr
    if age is not None:
        return 220 - age
    return DEFAULT_MAX_HR


def hr_zone_distribution(workouts: List[Workout], max_hr: int) -> Dict[str, Dict[str, float]]:
    """Распределение тренировок (число и суммарная длительность) по 5 зонам пульса.

    Тренировки без avg_hr в распределение не попадают.
    """
    zones: Dict[str, Dict[str, float]] = {
        name: {"count": 0, "duration_min": 0.0} for name, _, _ in HR_ZONES
    }
    if not max_hr:
        return zones

    for w in workouts:
        if w.avg_hr is None:
            continue
        ratio = w.avg_hr / max_hr
        if ratio < HR_ZONES[0][1]:
            continue
        for name, low, high in HR_ZONES:
            if ratio >= low and (high is None or ratio < high):
                zones[name]["count"] += 1
                zones[name]["duration_min"] += w.duration_min
                break

    for zone in zones.values():
        zone["duration_min"] = round(zone["duration_min"], 1)

    return zones


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_volume(workouts: List[Workout], reference_date: Optional[date] = None) -> Dict[str, object]:
    """Объём текущей недели (пн-вс) и сравнение со средним за предыдущие 4 недели."""
    if reference_date is None:
        reference_date = date.today()

    current_start = _week_start(reference_date)

    def week_workouts(start: date) -> List[Workout]:
        end = start + timedelta(days=6)
        return [w for w in workouts if start <= _parse_date(w.date) <= end]

    current = week_workouts(current_start)
    current_distance = sum(w.distance_km for w in current)
    current_duration_hours = sum(w.duration_min for w in current) / 60.0

    previous_distances = [
        sum(w.distance_km for w in week_workouts(current_start - timedelta(weeks=i)))
        for i in range(1, 5)
    ]
    previous_avg_distance = _avg(previous_distances)

    change_pct: Optional[float] = None
    if previous_avg_distance:
        change_pct = (current_distance - previous_avg_distance) / previous_avg_distance * 100

    return {
        "week_start": current_start.isoformat(),
        "week_end": (current_start + timedelta(days=6)).isoformat(),
        "distance_km": round(current_distance, 2),
        "duration_hours": round(current_duration_hours, 2),
        "count": len(current),
        "previous_avg_distance_km": round(previous_avg_distance, 2),
        "change_pct": round(change_pct, 1) if change_pct is not None else None,
    }


def _rising_hr_same_pace(ordered: List[Workout]) -> Optional[Dict[str, float]]:
    """Ищет рост среднего пульса при примерно той же скорости за N тренировок подряд
    (среди тех, где заданы и avg_hr, и avg_speed_kmh)."""
    candidates = [w for w in ordered if w.avg_hr is not None and w.avg_speed_kmh is not None]
    if len(candidates) < OVERTRAINING_STREAK:
        return None

    window = candidates[-OVERTRAINING_STREAK:]
    hr_values = [w.avg_hr for w in window]
    speed_values = [w.avg_speed_kmh for w in window]

    hr_rising = all(hr_values[i] < hr_values[i + 1] for i in range(len(hr_values) - 1))
    avg_speed = _avg(speed_values)
    speed_stable = avg_speed == 0 or (max(speed_values) - min(speed_values)) / avg_speed <= OVERTRAINING_SPEED_TOLERANCE

    if hr_rising and speed_stable:
        return {"hr_start": hr_values[0], "hr_end": hr_values[-1]}
    return None


def _trailing_streak_days(ordered: List[Workout]) -> int:
    """Длина непрерывной серии дней с тренировками, заканчивающейся последней тренировкой."""
    dates = sorted({_parse_date(w.date) for w in ordered})
    if not dates:
        return 0
    streak = 1
    for i in range(len(dates) - 1, 0, -1):
        if (dates[i] - dates[i - 1]).days == 1:
            streak += 1
        else:
            break
    return streak


def _general_trend_message(ordered: List[Workout]) -> str:
    group_size = 3 if len(ordered) >= 6 else 2
    recent = ordered[-group_size:]
    previous = ordered[-2 * group_size:-group_size]

    recent_distance = _avg([w.distance_km for w in recent])
    previous_distance = _avg([w.distance_km for w in previous])
    distance_change = (
        (recent_distance - previous_distance) / previous_distance if previous_distance else 0.0
    )

    recent_speeds = [w.avg_speed_kmh for w in recent if w.avg_speed_kmh is not None]
    previous_speeds = [w.avg_speed_kmh for w in previous if w.avg_speed_kmh is not None]
    speed_change = None
    if recent_speeds and previous_speeds:
        recent_speed = _avg(recent_speeds)
        previous_speed = _avg(previous_speeds)
        speed_change = (recent_speed - previous_speed) / previous_speed if previous_speed else 0.0

    if distance_change > CHANGE_THRESHOLD and (speed_change is None or speed_change >= -CHANGE_THRESHOLD):
        return (
            f"Прогресс растёт: средняя дистанция за последние тренировки выросла на "
            f"{distance_change * 100:.0f}% ({previous_distance:.1f} → {recent_distance:.1f} км) — "
            f"можно постепенно увеличивать нагрузку."
        )

    if distance_change < -CHANGE_THRESHOLD or (speed_change is not None and speed_change < -CHANGE_THRESHOLD):
        return (
            f"Нагрузка снизилась по сравнению с предыдущими тренировками "
            f"({previous_distance:.1f} → {recent_distance:.1f} км) — возможно, стоит отдохнуть."
        )

    return "Нагрузка стабильна: заметных изменений по дистанции и скорости не произошло."


def build_recommendations(
    workouts: List[Workout],
    max_hr: Optional[int] = None,
    reference_date: Optional[date] = None,
) -> List[str]:
    """2-4 текстовых пункта с рекомендациями, приоритет — сигналы перетренированности/паузы."""
    if len(workouts) < MIN_WORKOUTS:
        return ["Недостаточно данных для рекомендаций — загрузите больше тренировок (минимум 4)."]

    if reference_date is None:
        reference_date = date.today()
    if max_hr is None:
        max_hr = resolve_max_hr()

    ordered = sorted(workouts, key=lambda w: w.date)
    last_date = _parse_date(ordered[-1].date)
    days_since_last = (reference_date - last_date).days

    priority: List[str] = []
    secondary: List[str] = []

    if days_since_last > LONG_PAUSE_DAYS:
        priority.append(
            f"С последней тренировки прошло {days_since_last} дн. — начни с лёгкой нагрузки, "
            f"чтобы вернуться в форму постепенно."
        )
    else:
        hr_rise = _rising_hr_same_pace(ordered)
        if hr_rise:
            priority.append(
                f"Средний пульс вырос с {hr_rise['hr_start']:.0f} до {hr_rise['hr_end']:.0f} уд/мин "
                f"при похожем темпе за {OVERTRAINING_STREAK} тренировки подряд — признак накопленной "
                f"усталости, стоит взять день отдыха."
            )

        streak_days = _trailing_streak_days(ordered)
        if streak_days >= NO_REST_STREAK_DAYS:
            priority.append(
                f"{streak_days} дней подряд без отдыха — запланируй день восстановления."
            )

    weekly = weekly_volume(workouts, reference_date=reference_date)
    if weekly["change_pct"] is not None and weekly["change_pct"] > WEEKLY_GROWTH_WARNING_PCT:
        priority.append(
            f"Объём этой недели вырос на {weekly['change_pct']:.0f}% "
            f"({weekly['distance_km']:.1f} км против {weekly['previous_avg_distance_km']:.1f} км "
            f"в среднем за 4 прошлые недели) — рост больше 10% повышает риск травм, наращивай объём плавнее."
        )
    else:
        change_note = (
            f" ({weekly['change_pct']:+.0f}% к среднему за 4 недели)" if weekly["change_pct"] is not None else ""
        )
        secondary.append(
            f"На этой неделе: {weekly['distance_km']:.1f} км, {weekly['duration_hours']:.1f} ч, "
            f"{weekly['count']} тренировок{change_note}."
        )

    secondary.append(_general_trend_message(ordered))

    return (priority + secondary)[:4]
