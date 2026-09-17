import os

import pytest

from app.parser import CsvParseError, parse_csv

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV_PATH = os.path.join(FIXTURES_DIR, "sample_workouts.csv")


def read_sample() -> str:
    with open(SAMPLE_CSV_PATH, encoding="utf-8") as f:
        return f.read()


def test_parse_valid_csv_from_fixture():
    workouts = parse_csv(read_sample(), "user@example.com")

    assert len(workouts) == 10
    first, last = workouts[0], workouts[-1]

    assert first.user_email == "user@example.com"
    assert first.date == "2026-08-01"
    assert first.distance_km == pytest.approx(32.5)
    assert first.duration_min == pytest.approx(65)
    assert first.avg_speed_kmh == pytest.approx(30.0)
    assert first.avg_hr == pytest.approx(142)
    assert first.id is None

    assert last.date == "2026-08-25"
    assert last.distance_km == pytest.approx(40.0)
    assert last.duration_min == pytest.approx(82)


def test_parse_stamps_user_email_on_every_row():
    workouts = parse_csv(read_sample(), "someone@example.com")
    assert all(w.user_email == "someone@example.com" for w in workouts)


@pytest.mark.parametrize(
    "header",
    [
        "distance_km,duration_min\n1.0,2.0\n",  # без date
        "date,duration_min\n2026-01-01,2.0\n",  # без distance_km
        "date,distance_km\n2026-01-01,1.0\n",  # без duration_min
    ],
)
def test_missing_required_column_raises(header):
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(header, "user@example.com")
    assert "обязательные колонки" in str(exc_info.value)


def test_missing_required_column_message_lists_all_missing():
    csv_text = "avg_hr\n140\n"  # нет date, distance_km, duration_min
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    message = str(exc_info.value)
    assert "date" in message
    assert "distance_km" in message
    assert "duration_min" in message


def test_empty_file_raises():
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv("", "user@example.com")
    assert "Пустой CSV" in str(exc_info.value)


def test_header_only_no_data_rows_raises():
    csv_text = "date,distance_km,duration_min\n"
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    assert "не содержит" in str(exc_info.value)


def test_invalid_numeric_value_in_distance_km_raises():
    csv_text = "date,distance_km,duration_min\n2026-01-01,not-a-number,30\n"
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    message = str(exc_info.value)
    assert "distance_km" in message
    assert "Строка 2" in message


def test_invalid_numeric_value_in_duration_min_raises():
    csv_text = "date,distance_km,duration_min\n2026-01-01,10,thirty\n"
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    message = str(exc_info.value)
    assert "duration_min" in message
    assert "Строка 2" in message


def test_invalid_numeric_value_row_number_for_second_data_row():
    csv_text = "date,distance_km,duration_min\n2026-01-01,10,30\n2026-01-02,bad,40\n"
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    assert "Строка 3" in str(exc_info.value)


def test_missing_date_value_in_row_raises():
    csv_text = "date,distance_km,duration_min\n,10,30\n"
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    assert "отсутствует дата" in str(exc_info.value)


def test_extra_and_reordered_columns_are_ignored():
    csv_text = (
        "duration_min,note,distance_km,date,avg_hr,extra_col,avg_speed_kmh\n"
        "65,comment,32.5,2026-08-01,142,ignore-me,30.0\n"
    )
    workouts = parse_csv(csv_text, "user@example.com")

    assert len(workouts) == 1
    w = workouts[0]
    assert w.date == "2026-08-01"
    assert w.distance_km == pytest.approx(32.5)
    assert w.duration_min == pytest.approx(65)
    assert w.avg_speed_kmh == pytest.approx(30.0)
    assert w.avg_hr == pytest.approx(142)


def test_missing_optional_columns_default_to_none():
    csv_text = "date,distance_km,duration_min\n2026-01-01,10,30\n"
    workouts = parse_csv(csv_text, "user@example.com")

    assert workouts[0].avg_speed_kmh is None
    assert workouts[0].avg_hr is None


def test_empty_optional_value_becomes_none():
    csv_text = "date,distance_km,duration_min,avg_speed_kmh,avg_hr\n2026-01-01,10,30,,\n"
    workouts = parse_csv(csv_text, "user@example.com")

    assert workouts[0].avg_speed_kmh is None
    assert workouts[0].avg_hr is None


def test_invalid_numeric_value_in_optional_column_raises():
    csv_text = (
        "date,distance_km,duration_min,avg_hr\n2026-01-01,10,30,not-a-heart-rate\n"
    )
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(csv_text, "user@example.com")
    assert "avg_hr" in str(exc_info.value)


def test_whitespace_around_values_is_trimmed():
    csv_text = "date,distance_km,duration_min\n  2026-01-01  , 10.5 , 30 \n"
    workouts = parse_csv(csv_text, "user@example.com")

    assert workouts[0].date == "2026-01-01"
    assert workouts[0].distance_km == pytest.approx(10.5)
    assert workouts[0].duration_min == pytest.approx(30)
