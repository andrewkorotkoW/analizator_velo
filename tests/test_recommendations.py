import pytest

from app.models import Workout
from app.recommendations import (
    CHANGE_THRESHOLD,
    MIN_WORKOUTS,
    build_recommendation,
)

GROWING_TEXT = (
    "Прогресс растёт: средняя дистанция за последние тренировки увеличилась — "
    "можно постепенно увеличивать нагрузку."
)
RESTING_TEXT = (
    "Нагрузка снизилась по сравнению с предыдущими тренировками — "
    "возможно, стоит отдохнуть."
)
STABLE_TEXT = "Нагрузка стабильна: заметных изменений по дистанции и скорости не произошло."
NOT_ENOUGH_TEXT = "Недостаточно данных для рекомендаций — загрузите больше тренировок (минимум 4)."


def make_workout(date, distance_km, avg_speed_kmh=30.0, user_email="a@example.com"):
    return Workout(
        user_email=user_email,
        date=date,
        distance_km=distance_km,
        duration_min=60.0,
        avg_speed_kmh=avg_speed_kmh,
        avg_hr=140.0,
    )


def dated(n, start_day=1):
    """n тренировок с датами 2026-01-<start_day>, +1 день каждая."""
    return [f"2026-01-{start_day + i:02d}" for i in range(n)]


# --- Граничные случаи по количеству тренировок (0..3) не должны падать с исключением ---


def test_zero_workouts_returns_not_enough_message():
    assert build_recommendation([]) == NOT_ENOUGH_TEXT


def test_one_workout_returns_not_enough_message():
    workouts = [make_workout("2026-01-01", 10.0)]
    assert build_recommendation(workouts) == NOT_ENOUGH_TEXT


def test_two_workouts_returns_not_enough_message():
    workouts = [
        make_workout("2026-01-01", 10.0),
        make_workout("2026-01-02", 20.0),
    ]
    assert build_recommendation(workouts) == NOT_ENOUGH_TEXT


def test_three_workouts_returns_not_enough_message():
    dates = dated(3)
    workouts = [make_workout(d, 10.0 + i) for i, d in enumerate(dates)]
    assert build_recommendation(workouts) == NOT_ENOUGH_TEXT


def test_min_workouts_constant_is_four():
    # Явная проверка порога, от которого зависят все остальные тесты этого файла.
    assert MIN_WORKOUTS == 4


# --- Растущий прогресс ---


def test_four_workouts_growing_distance_gives_growth_recommendation():
    # group_size=2: recent=[3,4] avg=17.5, previous=[1,2] avg=10.5 -> +66%
    dates = dated(4)
    distances = [10.0, 11.0, 16.0, 19.0]
    workouts = [make_workout(d, dist) for d, dist in zip(dates, distances)]
    assert build_recommendation(workouts) == GROWING_TEXT


def test_six_workouts_uses_group_of_three_and_detects_growth():
    dates = dated(6)
    # previous group (idx 0-2): avg 10; recent group (idx 3-5): avg 20 -> +100%
    distances = [10.0, 10.0, 10.0, 20.0, 20.0, 20.0]
    workouts = [make_workout(d, dist) for d, dist in zip(dates, distances)]
    assert build_recommendation(workouts) == GROWING_TEXT


def test_growth_recognized_even_with_missing_speed_data():
    # avg_speed_kmh отсутствует у всех -> speed_change остаётся None и не мешает росту.
    dates = dated(4)
    distances = [10.0, 10.0, 20.0, 20.0]
    workouts = [
        make_workout(d, dist, avg_speed_kmh=None) for d, dist in zip(dates, distances)
    ]
    assert build_recommendation(workouts) == GROWING_TEXT


# --- Падающий прогресс ---


def test_four_workouts_falling_distance_gives_rest_recommendation():
    dates = dated(4)
    distances = [19.0, 18.0, 11.0, 10.0]
    workouts = [make_workout(d, dist) for d, dist in zip(dates, distances)]
    assert build_recommendation(workouts) == RESTING_TEXT


def test_falling_speed_alone_triggers_rest_recommendation_even_if_distance_flat():
    dates = dated(4)
    distances = [10.0, 10.0, 10.0, 10.0]
    speeds = [30.0, 30.0, 20.0, 20.0]
    workouts = [
        make_workout(d, dist, avg_speed_kmh=s)
        for d, dist, s in zip(dates, distances, speeds)
    ]
    assert build_recommendation(workouts) == RESTING_TEXT


# --- Стабильный прогресс ---


def test_stable_distance_and_speed_gives_neutral_recommendation():
    dates = dated(4)
    distances = [10.0, 10.1, 10.0, 10.05]
    workouts = [make_workout(d, dist) for d, dist in zip(dates, distances)]
    assert build_recommendation(workouts) == STABLE_TEXT


def test_change_exactly_at_threshold_is_not_counted_as_growth():
    # distance_change ровно CHANGE_THRESHOLD (не строго больше) -> не рост, а стабильно.
    dates = dated(4)
    previous = 100.0
    recent = previous * (1 + CHANGE_THRESHOLD)
    workouts = [
        make_workout(dates[0], previous),
        make_workout(dates[1], previous),
        make_workout(dates[2], recent),
        make_workout(dates[3], recent),
    ]
    assert build_recommendation(workouts) == STABLE_TEXT


# --- Прочие граничные случаи логики ---


def test_zero_previous_distance_does_not_raise_and_is_treated_as_no_change():
    # Документирует текущее поведение: деление на 0 предотвращено через `if previous_distance else 0.0`,
    # поэтому рост от нулевой базы засчитывается как "нет изменений" (стабильно), а не как рост.
    dates = dated(4)
    workouts = [
        make_workout(dates[0], 0.0),
        make_workout(dates[1], 0.0),
        make_workout(dates[2], 50.0),
        make_workout(dates[3], 50.0),
    ]
    assert build_recommendation(workouts) == STABLE_TEXT


def test_unsorted_input_is_sorted_by_date_before_comparison():
    # Тренировки переданы не по порядку дат -> функция должна сама отсортировать.
    dates = dated(4)
    distances = [10.0, 10.0, 19.0, 20.0]
    workouts = [make_workout(d, dist) for d, dist in zip(dates, distances)]
    shuffled = [workouts[2], workouts[0], workouts[3], workouts[1]]
    assert build_recommendation(shuffled) == GROWING_TEXT


def test_growing_distance_with_falling_speed_yields_rest_not_growth():
    # Документирует текущую логику: сильный рост дистанции при заметном падении
    # скорости не считается прогрессом (ветка роста требует speed_change >= -THRESHOLD),
    # а попадает в ветку "отдохнуть", поскольку speed_change < -THRESHOLD.
    dates = dated(4)
    distances = [10.0, 10.0, 20.0, 20.0]
    speeds = [30.0, 30.0, 15.0, 15.0]
    workouts = [
        make_workout(d, dist, avg_speed_kmh=s)
        for d, dist, s in zip(dates, distances, speeds)
    ]
    assert build_recommendation(workouts) == RESTING_TEXT


def test_does_not_mutate_input_list_order():
    dates = dated(4)
    distances = [10.0, 10.0, 20.0, 20.0]
    workouts = [make_workout(d, dist) for d, dist in zip(dates, distances)]
    shuffled = [workouts[3], workouts[1], workouts[2], workouts[0]]
    original_order = list(shuffled)
    build_recommendation(shuffled)
    assert shuffled == original_order
