from typing import List

from app.models import Workout

MIN_WORKOUTS = 4
CHANGE_THRESHOLD = 0.05


def _avg(values: List[float]) -> float:
    return sum(values) / len(values)


def build_recommendation(workouts: List[Workout]) -> str:
    """Сравнивает последние тренировки с предыдущими и возвращает текстовую рекомендацию."""
    if len(workouts) < MIN_WORKOUTS:
        return "Недостаточно данных для рекомендаций — загрузите больше тренировок (минимум 4)."

    ordered = sorted(workouts, key=lambda w: w.date)
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
        return "Прогресс растёт: средняя дистанция за последние тренировки увеличилась — можно постепенно увеличивать нагрузку."

    if distance_change < -CHANGE_THRESHOLD or (speed_change is not None and speed_change < -CHANGE_THRESHOLD):
        return "Нагрузка снизилась по сравнению с предыдущими тренировками — возможно, стоит отдохнуть."

    return "Нагрузка стабильна: заметных изменений по дистанции и скорости не произошло."
