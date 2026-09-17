import sqlite3

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
                  duration_min=30.0, avg_speed_kmh=20.0, avg_hr=140.0, source="csv"):
    return Workout(
        user_email=user_email,
        date=date,
        distance_km=distance_km,
        duration_min=duration_min,
        avg_speed_kmh=avg_speed_kmh,
        avg_hr=avg_hr,
        source=source,
    )


def make_user(email="a@example.com", password_hash="hash", **kwargs):
    return storage.create_user(email=email, password_hash=password_hash, **kwargs)


# =====================================================================
# users
# =====================================================================


def test_create_user_and_get_by_email():
    user = make_user(email="a@example.com", password_hash="h1", name="Anna", age=30, max_hr=190, weight=60.5)

    assert user.id is not None
    assert user.email == "a@example.com"
    assert user.name == "Anna"
    assert user.age == 30
    assert user.max_hr == 190
    assert user.weight == pytest.approx(60.5)

    fetched = storage.get_user_by_email("a@example.com")
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.password_hash == "h1"


def test_get_user_by_email_unknown_returns_none():
    assert storage.get_user_by_email("nobody@example.com") is None


def test_get_user_by_id_roundtrip():
    user = make_user(email="a@example.com")
    fetched = storage.get_user_by_id(user.id)
    assert fetched.email == "a@example.com"


def test_get_user_by_id_unknown_returns_none():
    assert storage.get_user_by_id(999999) is None


def test_create_user_minimal_fields_defaults_to_none():
    user = make_user(email="minimal@example.com", password_hash="h")
    assert user.name is None
    assert user.age is None
    assert user.max_hr is None
    assert user.weight is None


def test_create_user_duplicate_email_raises_integrity_error():
    make_user(email="dup@example.com")
    with pytest.raises(sqlite3.IntegrityError):
        make_user(email="dup@example.com")


def test_update_user_profile_changes_fields_and_returns_updated_user():
    user = make_user(email="a@example.com", name="Old", age=20, max_hr=180, weight=70.0)

    updated = storage.update_user_profile(user.id, name="New", age=25, max_hr=195, weight=68.5)

    assert updated.name == "New"
    assert updated.age == 25
    assert updated.max_hr == 195
    assert updated.weight == pytest.approx(68.5)

    refetched = storage.get_user_by_id(user.id)
    assert refetched.name == "New"


def test_update_user_profile_unknown_user_returns_none():
    assert storage.update_user_profile(999999, name="X") is None


def test_update_user_profile_does_not_change_email_or_password():
    user = make_user(email="a@example.com", password_hash="secret-hash")
    storage.update_user_profile(user.id, name="New Name")

    refetched = storage.get_user_by_id(user.id)
    assert refetched.email == "a@example.com"
    assert refetched.password_hash == "secret-hash"


# =====================================================================
# workouts <-> user_id
# =====================================================================


def test_save_and_get_workouts_by_user_id():
    user = make_user(email="a@example.com")
    workouts = [
        make_workout(date="2026-01-01", distance_km=10.0),
        make_workout(date="2026-01-02", distance_km=20.0),
    ]

    result = storage.save_workouts("a@example.com", workouts, user_id=user.id)
    assert result == {"saved": 2, "duplicates": 0}

    fetched = storage.get_workouts(user_id=user.id)
    assert len(fetched) == 2
    assert all(w.id is not None for w in fetched)


def test_get_workouts_by_user_id_sorted_ascending():
    user = make_user(email="a@example.com")
    workouts = [
        make_workout(date="2026-03-01"),
        make_workout(date="2026-01-01"),
        make_workout(date="2026-02-01"),
    ]
    storage.save_workouts("a@example.com", workouts, user_id=user.id)

    fetched = storage.get_workouts(user_id=user.id)
    dates = [w.date for w in fetched]
    assert dates == ["2026-01-01", "2026-02-01", "2026-03-01"]


def test_different_users_do_not_see_each_others_workouts_via_user_id():
    user_a = make_user(email="a@example.com")
    user_b = make_user(email="b@example.com")
    storage.save_workouts("a@example.com", [make_workout(user_email="a@example.com")], user_id=user_a.id)
    storage.save_workouts("b@example.com", [make_workout(user_email="b@example.com")], user_id=user_b.id)

    a_workouts = storage.get_workouts(user_id=user_a.id)
    b_workouts = storage.get_workouts(user_id=user_b.id)

    assert len(a_workouts) == 1
    assert len(b_workouts) == 1


def test_get_workouts_for_user_with_no_workouts_returns_empty_list():
    user = make_user(email="a@example.com")
    assert storage.get_workouts(user_id=user.id) == []


def test_save_empty_list_returns_zero_and_saves_nothing():
    user = make_user(email="a@example.com")
    result = storage.save_workouts("a@example.com", [], user_id=user.id)
    assert result == {"saved": 0, "duplicates": 0}
    assert storage.get_workouts(user_id=user.id) == []


def test_get_workouts_by_user_email_back_compat_when_no_user_id_given():
    workouts = [make_workout(date="2026-01-01")]
    storage.save_workouts("legacy@example.com", workouts, user_id=None)

    fetched = storage.get_workouts(user_email="legacy@example.com")
    assert len(fetched) == 1
    assert fetched[0].user_email == "legacy@example.com"


# =====================================================================
# дедупликация (та же дата + дистанция в пределах ±1%)
# =====================================================================


def test_duplicate_same_date_and_exact_distance_is_skipped():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id)

    result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id
    )
    assert result == {"saved": 0, "duplicates": 1}
    assert len(storage.get_workouts(user_id=user.id)) == 1


def test_duplicate_within_one_percent_tolerance_is_skipped():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id)

    result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-01", distance_km=100.9)], user_id=user.id
    )
    assert result == {"saved": 0, "duplicates": 1}


def test_duplicate_exactly_at_one_percent_boundary_is_still_a_duplicate():
    # abs(diff) <= abs(known) * 0.01 (граница включена).
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id)

    result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-01", distance_km=101.0)], user_id=user.id
    )
    assert result == {"saved": 0, "duplicates": 1}


def test_distance_just_beyond_one_percent_is_saved_as_new():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id)

    result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-01", distance_km=101.5)], user_id=user.id
    )
    assert result == {"saved": 1, "duplicates": 0}
    assert len(storage.get_workouts(user_id=user.id)) == 2


def test_same_distance_different_date_is_not_a_duplicate():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id)

    result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-02", distance_km=100.0)], user_id=user.id
    )
    assert result == {"saved": 1, "duplicates": 0}


def test_zero_distance_duplicate_only_matches_zero_distance():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=0.0)], user_id=user.id)

    dup_result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-01", distance_km=0.0)], user_id=user.id
    )
    assert dup_result == {"saved": 0, "duplicates": 1}

    nonzero_result = storage.save_workouts(
        "a@example.com", [make_workout(date="2026-01-01", distance_km=5.0)], user_id=user.id
    )
    assert nonzero_result == {"saved": 1, "duplicates": 0}


def test_dedup_is_scoped_to_user_id_not_shared_across_users():
    user_a = make_user(email="a@example.com")
    user_b = make_user(email="b@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user_a.id)

    # Тот же (дата, дистанция) для другого пользователя — не дубликат.
    result = storage.save_workouts(
        "b@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user_b.id
    )
    assert result == {"saved": 1, "duplicates": 0}


def test_batch_upload_deduplicates_within_itself_against_existing():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01", distance_km=100.0)], user_id=user.id)

    batch = [
        make_workout(date="2026-01-01", distance_km=100.5),  # дубль существующей
        make_workout(date="2026-01-02", distance_km=50.0),   # новая
    ]
    result = storage.save_workouts("a@example.com", batch, user_id=user.id)
    assert result == {"saved": 1, "duplicates": 1}
    assert len(storage.get_workouts(user_id=user.id)) == 2


# =====================================================================
# delete_workout
# =====================================================================


def test_delete_workout_removes_own_workout_and_returns_true():
    user = make_user(email="a@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01")], user_id=user.id)
    workout_id = storage.get_workouts(user_id=user.id)[0].id

    assert storage.delete_workout(user.id, workout_id) is True
    assert storage.get_workouts(user_id=user.id) == []


def test_delete_workout_of_another_user_returns_false_and_does_not_delete():
    user_a = make_user(email="a@example.com")
    user_b = make_user(email="b@example.com")
    storage.save_workouts("a@example.com", [make_workout(date="2026-01-01")], user_id=user_a.id)
    workout_id = storage.get_workouts(user_id=user_a.id)[0].id

    assert storage.delete_workout(user_b.id, workout_id) is False
    assert len(storage.get_workouts(user_id=user_a.id)) == 1


def test_delete_workout_unknown_id_returns_false():
    user = make_user(email="a@example.com")
    assert storage.delete_workout(user.id, 999999) is False


# =====================================================================
# has_legacy_workouts / migrate_email_to_user
# =====================================================================


def test_has_legacy_workouts_true_when_unassigned_rows_exist():
    storage.save_workouts("legacy@example.com", [make_workout(user_email="legacy@example.com")], user_id=None)
    assert storage.has_legacy_workouts("legacy@example.com") is True


def test_has_legacy_workouts_false_when_no_rows_at_all():
    assert storage.has_legacy_workouts("nobody@example.com") is False


def test_has_legacy_workouts_false_once_already_assigned_to_a_user():
    user = make_user(email="legacy@example.com")
    storage.save_workouts("legacy@example.com", [make_workout(user_email="legacy@example.com")], user_id=user.id)
    assert storage.has_legacy_workouts("legacy@example.com") is False


def test_migrate_email_to_user_assigns_only_unassigned_rows_and_returns_count():
    storage.save_workouts(
        "legacy@example.com",
        [
            make_workout(user_email="legacy@example.com", date="2026-01-01"),
            make_workout(user_email="legacy@example.com", date="2026-01-02"),
        ],
        user_id=None,
    )
    user = make_user(email="legacy@example.com")

    migrated_count = storage.migrate_email_to_user("legacy@example.com", user.id)

    assert migrated_count == 2
    assert len(storage.get_workouts(user_id=user.id)) == 2
    assert storage.has_legacy_workouts("legacy@example.com") is False


def test_migrate_email_to_user_does_not_touch_rows_already_assigned_to_another_user():
    user_a = make_user(email="a@example.com")
    user_b = make_user(email="legacy@example.com")

    storage.save_workouts(
        "legacy@example.com", [make_workout(user_email="legacy@example.com", date="2026-01-01")], user_id=user_a.id
    )

    migrated_count = storage.migrate_email_to_user("legacy@example.com", user_b.id)

    assert migrated_count == 0
    assert len(storage.get_workouts(user_id=user_a.id)) == 1
    assert storage.get_workouts(user_id=user_b.id) == []


def test_migrate_email_to_user_with_no_legacy_rows_returns_zero():
    user = make_user(email="a@example.com")
    assert storage.migrate_email_to_user("a@example.com", user.id) == 0


def test_migrate_email_to_user_only_matches_given_email():
    storage.save_workouts("other@example.com", [make_workout(user_email="other@example.com")], user_id=None)
    user = make_user(email="a@example.com")

    migrated_count = storage.migrate_email_to_user("a@example.com", user.id)

    assert migrated_count == 0
    assert storage.get_workouts(user_id=user.id) == []
