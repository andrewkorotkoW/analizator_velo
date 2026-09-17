import pytest

import app.storage as storage
from app.models import Workout


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Каждый тест получает свою пустую БД, чтобы не пересекаться с другими."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    storage.init_db()
    yield


def make_workout(user_email="a@example.com", date="2026-01-01", distance_km=10.0,
                  duration_min=30.0, avg_speed_kmh=20.0, avg_hr=140.0):
    return Workout(
        user_email=user_email,
        date=date,
        distance_km=distance_km,
        duration_min=duration_min,
        avg_speed_kmh=avg_speed_kmh,
        avg_hr=avg_hr,
    )


def test_save_and_get_roundtrip():
    workouts = [
        make_workout(date="2026-01-01", distance_km=10.0),
        make_workout(date="2026-01-02", distance_km=20.0),
    ]

    saved = storage.save_workouts("a@example.com", workouts)
    assert saved == 2

    fetched = storage.get_workouts("a@example.com")
    assert len(fetched) == 2

    for original, got in zip(workouts, fetched):
        assert got.id is not None
        assert got.user_email == original.user_email
        assert got.date == original.date
        assert got.distance_km == pytest.approx(original.distance_km)
        assert got.duration_min == pytest.approx(original.duration_min)
        assert got.avg_speed_kmh == pytest.approx(original.avg_speed_kmh)
        assert got.avg_hr == pytest.approx(original.avg_hr)


def test_save_preserves_optional_none_fields():
    workout = Workout(
        user_email="a@example.com",
        date="2026-01-01",
        distance_km=10.0,
        duration_min=30.0,
        avg_speed_kmh=None,
        avg_hr=None,
    )
    storage.save_workouts("a@example.com", [workout])

    fetched = storage.get_workouts("a@example.com")
    assert fetched[0].avg_speed_kmh is None
    assert fetched[0].avg_hr is None


def test_get_workouts_sorted_by_date_ascending():
    workouts = [
        make_workout(date="2026-03-01"),
        make_workout(date="2026-01-01"),
        make_workout(date="2026-02-01"),
    ]
    storage.save_workouts("a@example.com", workouts)

    fetched = storage.get_workouts("a@example.com")
    dates = [w.date for w in fetched]
    assert dates == sorted(dates)
    assert dates == ["2026-01-01", "2026-02-01", "2026-03-01"]


def test_different_users_do_not_see_each_others_workouts():
    storage.save_workouts("a@example.com", [make_workout(user_email="a@example.com")])
    storage.save_workouts("b@example.com", [make_workout(user_email="b@example.com")])

    a_workouts = storage.get_workouts("a@example.com")
    b_workouts = storage.get_workouts("b@example.com")

    assert len(a_workouts) == 1
    assert len(b_workouts) == 1
    assert all(w.user_email == "a@example.com" for w in a_workouts)
    assert all(w.user_email == "b@example.com" for w in b_workouts)


def test_get_workouts_for_unknown_user_returns_empty_list():
    assert storage.get_workouts("nobody@example.com") == []


def test_save_empty_list_returns_zero_and_saves_nothing():
    saved = storage.save_workouts("a@example.com", [])
    assert saved == 0
    assert storage.get_workouts("a@example.com") == []


def test_repeated_upload_appends_rather_than_replaces():
    """Фиксирует ТЕКУЩЕЕ поведение save_workouts: чистый INSERT без дедупликации
    и без замены существующих записей. Повторная загрузка одного и того же CSV
    приводит к дублированию всех строк (см. список дефектов в резюме задачи —
    возможно, поведение должно быть другим: замена / upsert по (user_email, date))."""
    workouts = [make_workout(date="2026-01-01", distance_km=10.0)]

    storage.save_workouts("a@example.com", workouts)
    storage.save_workouts("a@example.com", workouts)

    fetched = storage.get_workouts("a@example.com")
    assert len(fetched) == 2
    assert fetched[0].date == fetched[1].date == "2026-01-01"
    assert fetched[0].id != fetched[1].id


def test_save_workouts_for_one_user_does_not_disturb_existing_rows_of_another_user():
    storage.save_workouts("a@example.com", [make_workout(user_email="a@example.com", date="2026-01-01")])
    storage.save_workouts("b@example.com", [make_workout(user_email="b@example.com", date="2026-02-01")])

    a_after = storage.get_workouts("a@example.com")
    assert len(a_after) == 1
    assert a_after[0].date == "2026-01-01"
