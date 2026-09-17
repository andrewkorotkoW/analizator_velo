from datetime import date, timedelta

import pytest

from app.models import Workout
from app.recommendations import (
    DEFAULT_MAX_HR,
    LONG_PAUSE_DAYS,
    MIN_WORKOUTS,
    NO_REST_STREAK_DAYS,
    OVERTRAINING_SPEED_TOLERANCE,
    OVERTRAINING_STREAK,
    WEEKLY_GROWTH_WARNING_PCT,
    build_recommendations,
    hr_zone_distribution,
    resolve_max_hr,
    weekly_volume,
)

NOT_ENOUGH_TEXT = "Недостаточно данных для рекомендаций — загрузите больше тренировок (минимум 4)."


def make_workout(date_str, distance_km=10.0, duration_min=30.0, avg_speed_kmh=20.0,
                  avg_hr=140.0, user_email="a@example.com"):
    return Workout(
        user_email=user_email,
        date=date_str,
        distance_km=distance_km,
        duration_min=duration_min,
        avg_speed_kmh=avg_speed_kmh,
        avg_hr=avg_hr,
    )


def dated(n, start_day=1):
    return [f"2026-01-{start_day + i:02d}" for i in range(n)]


# =====================================================================
# resolve_max_hr
# =====================================================================


def test_resolve_max_hr_uses_explicit_value_when_given():
    assert resolve_max_hr(user_max_hr=175, age=30) == 175


def test_resolve_max_hr_computed_from_age_when_no_explicit_value():
    assert resolve_max_hr(user_max_hr=None, age=30) == 190  # 220-30


def test_resolve_max_hr_defaults_when_neither_given():
    assert resolve_max_hr(user_max_hr=None, age=None) == DEFAULT_MAX_HR


def test_resolve_max_hr_default_constant_is_190():
    assert DEFAULT_MAX_HR == 190


def test_resolve_max_hr_explicit_value_wins_even_with_zero_age():
    # 0 — валидный (хоть и странный) возраст; главное что явный max_hr всё равно приоритетнее.
    assert resolve_max_hr(user_max_hr=200, age=0) == 200


# =====================================================================
# hr_zone_distribution
# =====================================================================


@pytest.mark.parametrize(
    "avg_hr,expected_zone",
    [
        (100, "Z1"),  # ratio exactly 0.50 -> нижняя граница Z1 включена
        (110, "Z1"),
        (120, "Z2"),  # ratio exactly 0.60 -> граница Z1/Z2, попадает в Z2
        (130, "Z2"),
        (140, "Z3"),  # ratio exactly 0.70
        (150, "Z3"),
        (160, "Z4"),  # ratio exactly 0.80
        (170, "Z4"),
        (180, "Z5"),  # ratio exactly 0.90
        (200, "Z5"),  # ratio > 1.0 — всё равно Z5 (верхней границы нет)
    ],
)
def test_hr_zone_distribution_boundaries(avg_hr, expected_zone):
    # max_hr = 200, границы зон в уд/мин: 100/120/140/160/180
    workouts = [make_workout("2026-01-01", avg_hr=avg_hr, duration_min=45.0)]
    zones = hr_zone_distribution(workouts, max_hr=200)

    for name, zone in zones.items():
        if name == expected_zone:
            assert zone["count"] == 1
            assert zone["duration_min"] == pytest.approx(45.0)
        else:
            assert zone["count"] == 0


def test_hr_zone_distribution_below_z1_lower_bound_is_excluded_entirely():
    workouts = [make_workout("2026-01-01", avg_hr=90, duration_min=30.0)]  # ratio 0.45 < 0.50
    zones = hr_zone_distribution(workouts, max_hr=200)
    assert all(z["count"] == 0 for z in zones.values())


def test_hr_zone_distribution_ignores_workouts_without_avg_hr():
    workouts = [make_workout("2026-01-01", avg_hr=None)]
    zones = hr_zone_distribution(workouts, max_hr=200)
    assert all(z["count"] == 0 for z in zones.values())


def test_hr_zone_distribution_aggregates_multiple_workouts_in_same_zone():
    workouts = [
        make_workout("2026-01-01", avg_hr=145, duration_min=30.0),
        make_workout("2026-01-02", avg_hr=150, duration_min=60.0),
    ]
    zones = hr_zone_distribution(workouts, max_hr=200)
    assert zones["Z3"]["count"] == 2
    assert zones["Z3"]["duration_min"] == pytest.approx(90.0)


def test_hr_zone_distribution_returns_all_five_zones_even_when_empty():
    zones = hr_zone_distribution([], max_hr=190)
    assert set(zones.keys()) == {"Z1", "Z2", "Z3", "Z4", "Z5"}


def test_hr_zone_distribution_with_zero_max_hr_returns_empty_zones_without_crashing():
    workouts = [make_workout("2026-01-01", avg_hr=140)]
    zones = hr_zone_distribution(workouts, max_hr=0)
    assert all(z["count"] == 0 for z in zones.values())


# =====================================================================
# weekly_volume
# =====================================================================


def test_weekly_volume_counts_only_current_week_monday_to_sunday():
    # Понедельник 2026-01-05
    reference = date(2026, 1, 8)  # четверг той же недели
    workouts = [
        make_workout("2026-01-05", distance_km=10.0, duration_min=60.0),  # в неделе
        make_workout("2026-01-08", distance_km=20.0, duration_min=90.0),  # в неделе
        make_workout("2026-01-04", distance_km=99.0),  # воскресенье прошлой недели — не в неделе
        make_workout("2026-01-12", distance_km=99.0),  # следующий понедельник — не в неделе
    ]
    result = weekly_volume(workouts, reference_date=reference)

    assert result["week_start"] == "2026-01-05"
    assert result["week_end"] == "2026-01-11"
    assert result["distance_km"] == pytest.approx(30.0)
    assert result["duration_hours"] == pytest.approx(150.0 / 60.0)
    assert result["count"] == 2


def test_weekly_volume_change_pct_compares_to_average_of_previous_four_weeks():
    reference = date(2026, 2, 2)  # понедельник
    workouts = [make_workout("2026-02-02", distance_km=44.0)]
    # Предыдущие 4 недели: по 10 км каждая -> среднее 10.
    for i in range(1, 5):
        week_monday = reference - timedelta(weeks=i)
        workouts.append(make_workout(week_monday.isoformat(), distance_km=10.0))

    result = weekly_volume(workouts, reference_date=reference)

    assert result["previous_avg_distance_km"] == pytest.approx(10.0)
    assert result["change_pct"] == pytest.approx(340.0)  # (44-10)/10*100


def test_weekly_volume_change_pct_none_when_no_previous_history():
    reference = date(2026, 2, 2)
    workouts = [make_workout("2026-02-02", distance_km=10.0)]
    result = weekly_volume(workouts, reference_date=reference)
    assert result["change_pct"] is None
    assert result["previous_avg_distance_km"] == 0.0


def test_weekly_volume_empty_current_week_still_returns_zero_stats():
    reference = date(2026, 3, 2)
    result = weekly_volume([], reference_date=reference)
    assert result["distance_km"] == 0.0
    assert result["count"] == 0


# =====================================================================
# build_recommendations — недостаточно данных
# =====================================================================


def test_min_workouts_constant_is_four():
    assert MIN_WORKOUTS == 4


@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_fewer_than_min_workouts_returns_single_not_enough_message(n):
    dates = dated(n)
    workouts = [make_workout(d) for d in dates]
    result = build_recommendations(workouts)
    assert result == [NOT_ENOUGH_TEXT]


def test_recommendations_list_has_between_two_and_four_items_for_normal_case():
    dates = dated(4)
    workouts = [make_workout(d, distance_km=10.0) for d in dates]
    reference = date(2026, 1, 10)
    result = build_recommendations(workouts, reference_date=reference)
    assert 2 <= len(result) <= 4


# =====================================================================
# build_recommendations — длинная пауза (>7 дней)
# =====================================================================


def test_long_pause_days_constant_is_seven():
    assert LONG_PAUSE_DAYS == 7


def test_long_pause_over_seven_days_triggers_priority_message():
    dates = dated(4)
    workouts = [make_workout(d, distance_km=10.0) for d in dates]
    last_date = date(2026, 1, 4)
    reference = last_date + timedelta(days=8)  # 8 дней > 7

    result = build_recommendations(workouts, reference_date=reference)
    assert "8 дн." in result[0]
    assert "лёгкой нагрузки" in result[0]


def test_pause_of_exactly_seven_days_does_not_trigger_pause_message():
    dates = dated(4)
    workouts = [make_workout(d, distance_km=10.0) for d in dates]
    last_date = date(2026, 1, 4)
    reference = last_date + timedelta(days=7)  # ровно 7, не > 7

    result = build_recommendations(workouts, reference_date=reference)
    assert not any("лёгкой нагрузки" in item for item in result)


def test_long_pause_suppresses_overtraining_checks():
    # Даже если паттерн похож на перетренированность, при длинной паузе
    # приоритет отдаётся сообщению о паузе (ветка else пропускается).
    dates = dated(4)
    hr_values = [130, 140, 150, 160]
    speeds = [20.0, 20.0, 20.0, 20.0]
    workouts = [
        make_workout(d, distance_km=10.0, avg_speed_kmh=s, avg_hr=h)
        for d, s, h in zip(dates, speeds, hr_values)
    ]
    reference = date(2026, 1, 4) + timedelta(days=10)

    result = build_recommendations(workouts, reference_date=reference)
    assert "лёгкой нагрузки" in result[0]
    assert not any("накопленной" in item for item in result)
    assert not any("дней подряд без отдыха" in item for item in result)


# =====================================================================
# build_recommendations — рост пульса при стабильном темпе
# =====================================================================


def test_overtraining_streak_constant_is_three():
    assert OVERTRAINING_STREAK == 3


def test_rising_hr_with_stable_pace_over_three_workouts_triggers_priority_message():
    dates = dated(4)
    hr_values = [130.0, 140.0, 150.0, 160.0]
    speeds = [25.0, 25.0, 25.1, 25.0]
    workouts = [
        make_workout(d, distance_km=10.0, avg_speed_kmh=s, avg_hr=h)
        for d, s, h in zip(dates, speeds, hr_values)
    ]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    # Окно — последние OVERTRAINING_STREAK(3) тренировки: hr 140 -> 160.
    assert any("накопленной" in item and "140" in item and "160" in item for item in result)


def test_falling_hr_does_not_trigger_overtraining_message():
    dates = dated(4)
    hr_values = [160.0, 150.0, 140.0, 130.0]
    speeds = [25.0, 25.0, 25.0, 25.0]
    workouts = [
        make_workout(d, distance_km=10.0, avg_speed_kmh=s, avg_hr=h)
        for d, s, h in zip(dates, speeds, hr_values)
    ]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert not any("накопленной" in item for item in result)


def test_speed_change_within_tolerance_still_counts_as_stable():
    # Окно перетренированности — последние OVERTRAINING_STREAK(3) тренировки (индексы 1,2,3).
    # (max-min)/avg внутри окна заметно меньше OVERTRAINING_SPEED_TOLERANCE -> speed_stable True.
    dates = dated(4)
    hr_values = [130.0, 140.0, 150.0, 160.0]
    speeds = [999.0, 20.0, 20.0, 20.0 * (1 + OVERTRAINING_SPEED_TOLERANCE / 2)]
    workouts = [
        make_workout(d, distance_km=10.0, avg_speed_kmh=s, avg_hr=h)
        for d, s, h in zip(dates, speeds, hr_values)
    ]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("накопленной" in item for item in result)


def test_speed_change_just_beyond_tolerance_does_not_trigger_overtraining_message():
    dates = dated(4)
    hr_values = [130.0, 140.0, 150.0, 160.0]
    speeds = [20.0, 20.0, 20.0, 30.0]  # заметно выросла скорость — не "тот же темп"
    workouts = [
        make_workout(d, distance_km=10.0, avg_speed_kmh=s, avg_hr=h)
        for d, s, h in zip(dates, speeds, hr_values)
    ]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert not any("накопленной" in item for item in result)


def test_overtraining_check_ignores_workouts_missing_hr_or_speed():
    # Первая тренировка без avg_hr не должна учитываться в окне последних 3.
    dates = dated(4)
    workouts = [
        make_workout(dates[0], avg_hr=None, avg_speed_kmh=20.0),
        make_workout(dates[1], avg_hr=130.0, avg_speed_kmh=20.0),
        make_workout(dates[2], avg_hr=140.0, avg_speed_kmh=20.0),
        make_workout(dates[3], avg_hr=150.0, avg_speed_kmh=20.0),
    ]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("накопленной" in item for item in result)


# =====================================================================
# build_recommendations — серия дней без отдыха
# =====================================================================


def test_no_rest_streak_constant_is_five():
    assert NO_REST_STREAK_DAYS == 5


def test_five_consecutive_days_triggers_no_rest_message():
    dates = dated(5)  # 5 подряд идущих дней
    workouts = [make_workout(d, distance_km=10.0, avg_hr=None, avg_speed_kmh=None) for d in dates]
    reference = date(2026, 1, 5)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("5 дней подряд без отдыха" in item for item in result)


def test_four_consecutive_days_does_not_trigger_no_rest_message():
    dates = dated(4)
    workouts = [make_workout(d, distance_km=10.0, avg_hr=None, avg_speed_kmh=None) for d in dates]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert not any("дней подряд без отдыха" in item for item in result)


def test_streak_is_measured_trailing_from_last_workout_not_whole_history():
    # 4 тренировки: две подряд в начале, разрыв, потом ещё не хватает дней подряд в конце.
    dates = ["2026-01-01", "2026-01-02", "2026-01-10", "2026-01-11"]
    workouts = [make_workout(d, distance_km=10.0, avg_hr=None, avg_speed_kmh=None) for d in dates]
    reference = date(2026, 1, 11)

    result = build_recommendations(workouts, reference_date=reference)
    assert not any("дней подряд без отдыха" in item for item in result)


def test_hr_rise_and_no_rest_streak_can_both_appear_as_priority_items():
    dates = dated(5)
    hr_values = [120.0, 130.0, 140.0, 150.0, 160.0]
    workouts = [
        make_workout(d, distance_km=10.0, avg_speed_kmh=20.0, avg_hr=h)
        for d, h in zip(dates, hr_values)
    ]
    reference = date(2026, 1, 5)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("накопленной" in item for item in result)
    assert any("5 дней подряд без отдыха" in item for item in result)


# =====================================================================
# build_recommendations — рост объёма за неделю (>10%)
# =====================================================================


def test_weekly_growth_warning_threshold_is_ten_percent():
    assert WEEKLY_GROWTH_WARNING_PCT == 10.0


def test_weekly_growth_over_ten_percent_triggers_priority_message():
    reference = date(2026, 2, 2)  # понедельник
    workouts = [make_workout("2026-02-02", distance_km=22.0, avg_hr=None, avg_speed_kmh=None)]
    for i in range(1, 5):
        week_monday = reference - timedelta(weeks=i)
        workouts.append(
            make_workout(week_monday.isoformat(), distance_km=10.0, avg_hr=None, avg_speed_kmh=None)
        )

    result = build_recommendations(workouts, reference_date=reference)
    assert any("рост больше 10%" in item for item in result)


def test_weekly_growth_exactly_ten_percent_is_not_a_warning():
    reference = date(2026, 2, 2)
    workouts = [make_workout("2026-02-02", distance_km=11.0, avg_hr=None, avg_speed_kmh=None)]
    for i in range(1, 5):
        week_monday = reference - timedelta(weeks=i)
        workouts.append(
            make_workout(week_monday.isoformat(), distance_km=10.0, avg_hr=None, avg_speed_kmh=None)
        )

    result = build_recommendations(workouts, reference_date=reference)
    assert not any("рост больше 10%" in item for item in result)
    # Вместо предупреждения — обычная сводка по неделе.
    assert any("На этой неделе" in item for item in result)


def test_weekly_summary_present_when_growth_not_flagged():
    dates = dated(4)
    workouts = [make_workout(d, distance_km=10.0) for d in dates]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("На этой неделе" in item for item in result)


# =====================================================================
# build_recommendations — общий тренд (растёт/падает/стабильно)
# =====================================================================


def test_general_trend_growing_is_reported():
    dates = dated(4)
    distances = [10.0, 11.0, 20.0, 21.0]
    workouts = [make_workout(d, distance_km=dist) for d, dist in zip(dates, distances)]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("Прогресс растёт" in item for item in result)


def test_general_trend_falling_is_reported():
    dates = dated(4)
    distances = [20.0, 21.0, 10.0, 11.0]
    workouts = [make_workout(d, distance_km=dist) for d, dist in zip(dates, distances)]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("снизилась" in item for item in result)


def test_general_trend_stable_is_reported():
    dates = dated(4)
    distances = [10.0, 10.1, 10.0, 10.05]
    workouts = [make_workout(d, distance_km=dist) for d, dist in zip(dates, distances)]
    reference = date(2026, 1, 4)

    result = build_recommendations(workouts, reference_date=reference)
    assert any("стабильна" in item for item in result)


# =====================================================================
# build_recommendations — прочее
# =====================================================================


def test_recommendations_result_capped_at_four_items():
    # Комбинация: рост пульса + серия без отдыха + рост объёма недели + тренд = 4 кандидата.
    dates = dated(5)
    hr_values = [120.0, 130.0, 140.0, 150.0, 160.0]
    reference = date(2026, 1, 5)  # вторник — недельный объём считается с понедельника 2026-01-05
    workouts = [
        make_workout(d, distance_km=20.0, avg_speed_kmh=20.0, avg_hr=h)
        for d, h in zip(dates, hr_values)
    ]
    for i in range(1, 5):
        week_monday = date(2026, 1, 5) - timedelta(weeks=i)
        workouts.append(
            make_workout(week_monday.isoformat(), distance_km=5.0, avg_speed_kmh=20.0, avg_hr=100.0)
        )

    result = build_recommendations(workouts, reference_date=reference)
    assert len(result) <= 4


def test_unsorted_input_is_sorted_by_date_before_analysis():
    dates = dated(4)
    distances = [10.0, 11.0, 20.0, 21.0]
    workouts = [make_workout(d, distance_km=dist) for d, dist in zip(dates, distances)]
    shuffled = [workouts[2], workouts[0], workouts[3], workouts[1]]
    reference = date(2026, 1, 4)

    result = build_recommendations(shuffled, reference_date=reference)
    assert any("Прогресс растёт" in item for item in result)


def test_does_not_mutate_input_list_order():
    dates = dated(4)
    distances = [10.0, 10.0, 20.0, 20.0]
    workouts = [make_workout(d, distance_km=dist) for d, dist in zip(dates, distances)]
    shuffled = [workouts[3], workouts[1], workouts[2], workouts[0]]
    original_order = list(shuffled)

    build_recommendations(shuffled, reference_date=date(2026, 1, 4))
    assert shuffled == original_order


def test_uses_default_max_hr_when_max_hr_not_passed():
    # Не должно падать при отсутствии max_hr — используется resolve_max_hr() по умолчанию.
    dates = dated(4)
    workouts = [make_workout(d, distance_km=10.0) for d in dates]
    result = build_recommendations(workouts, max_hr=None, reference_date=date(2026, 1, 4))
    assert isinstance(result, list)
    assert len(result) >= 1
