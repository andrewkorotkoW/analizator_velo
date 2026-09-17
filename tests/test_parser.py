import datetime
import math
import os

import pytest

from app.parser import (
    CsvParseError,
    FitParseError,
    GpxParseError,
    detect_file_type,
    parse_csv,
    parse_file,
    parse_fit,
    parse_gpx,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV_PATH = os.path.join(FIXTURES_DIR, "sample_workouts.csv")
SAMPLE_GPX_PATH = os.path.join(FIXTURES_DIR, "sample_track.gpx")

EARTH_RADIUS_KM = 6371.0088


def read_sample() -> str:
    with open(SAMPLE_CSV_PATH, encoding="utf-8") as f:
        return f.read()


def read_sample_gpx_bytes() -> bytes:
    with open(SAMPLE_GPX_PATH, "rb") as f:
        return f.read()


# =====================================================================
# CSV
# =====================================================================


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
    assert first.source == "csv"

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


# =====================================================================
# GPX
# =====================================================================


def _haversine_km_reference(lat1, lon1, lat2, lon2):
    """Независимая (от app.parser) реализация гаверсинуса — эталон для теста."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _moving_average_reference(values, window):
    n = len(values)
    half = window // 2
    result = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        chunk = values[lo:hi]
        result.append(sum(chunk) / len(chunk))
    return result


def _elevation_gain_reference(elevations, smoothing_window=3):
    if len(elevations) < 2:
        return None
    values = elevations
    if len(elevations) >= smoothing_window:
        values = _moving_average_reference(elevations, smoothing_window)
    gain = 0.0
    for prev, cur in zip(values, values[1:]):
        if cur > prev:
            gain += cur - prev
    return gain


# Точки эталонного трека (см. tests/fixtures/sample_track.gpx):
# та же долгота у всех точек, поэтому гаверсинус между соседними точками
# вырождается в R * дельта_широты_в_радианах — считаем это отдельно, без
# использования внутренностей app.parser.
_TRACK_POINTS = [
    (45.0000000, 0.0, 100, "2026-08-01T10:00:00Z", 120),
    (45.0009000, 0.0, 102, "2026-08-01T10:00:10Z", 125),
    (45.0018000, 0.0, 101, "2026-08-01T10:00:20Z", 130),
    (45.0018000, 0.0, 104, "2026-08-01T10:01:40Z", 128),  # пауза 80с (>30с)
    (45.0027000, 0.0, 103, "2026-08-01T10:01:50Z", 135),
]


def test_parse_gpx_computes_distance_duration_speed_elevation_hr_and_date():
    workouts = parse_gpx(read_sample_gpx_bytes(), "user@example.com")

    assert len(workouts) == 1
    w = workouts[0]

    expected_distance = sum(
        _haversine_km_reference(a[0], a[1], b[0], b[1])
        for a, b in zip(_TRACK_POINTS, _TRACK_POINTS[1:])
    )
    assert w.distance_km == pytest.approx(expected_distance)

    # 10:00:00 -> 10:01:50 = 110 секунд = 1.8333... мин
    assert w.duration_min == pytest.approx(110 / 60)

    # Время в движении исключает паузу 80с (>30с): 10+10+10 = 30с = 1/120 ч
    expected_moving_hours = 30 / 3600
    expected_speed = expected_distance / expected_moving_hours
    assert w.avg_speed_kmh == pytest.approx(expected_speed)

    expected_gain = _elevation_gain_reference([p[2] for p in _TRACK_POINTS])
    assert w.elevation_gain_m == pytest.approx(expected_gain)

    expected_avg_hr = sum(p[4] for p in _TRACK_POINTS) / len(_TRACK_POINTS)
    assert w.avg_hr == pytest.approx(expected_avg_hr)

    assert w.date == "2026-08-01"
    assert w.user_email == "user@example.com"
    assert w.source == "gpx"


def _build_gpx(points, hr_style="gpxtpx"):
    """points: список (lat, lon, ele_or_None, time_iso_or_None, hr_or_None)."""
    trkpts = []
    for lat, lon, ele, time_iso, hr in points:
        parts = [f'<trkpt lat="{lat}" lon="{lon}">']
        if ele is not None:
            parts.append(f"<ele>{ele}</ele>")
        if time_iso is not None:
            parts.append(f"<time>{time_iso}</time>")
        if hr is not None:
            if hr_style == "gpxtpx":
                parts.append(
                    "<extensions><gpxtpx:TrackPointExtension>"
                    f"<gpxtpx:hr>{hr}</gpxtpx:hr>"
                    "</gpxtpx:TrackPointExtension></extensions>"
                )
            else:
                parts.append(f"<extensions><hr>{hr}</hr></extensions>")
        parts.append("</trkpt>")
        trkpts.append("".join(parts))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
        "<trk><trkseg>" + "".join(trkpts) + "</trkseg></trk></gpx>"
    ).encode("utf-8")


def test_parse_gpx_raises_on_malformed_xml():
    with pytest.raises(GpxParseError):
        parse_gpx(b"this is not xml at all <<<", "user@example.com")


def test_parse_gpx_raises_when_zero_timed_points():
    content = _build_gpx(
        [
            (45.0, 0.0, 100, None, None),
            (45.001, 0.0, 101, None, None),
        ]
    )
    with pytest.raises(GpxParseError) as exc_info:
        parse_gpx(content, "user@example.com")
    assert "меньше двух" in str(exc_info.value)


def test_parse_gpx_raises_when_exactly_one_timed_point():
    content = _build_gpx(
        [
            (45.0, 0.0, 100, "2026-08-01T10:00:00Z", None),
            (45.001, 0.0, 101, None, None),
        ]
    )
    with pytest.raises(GpxParseError) as exc_info:
        parse_gpx(content, "user@example.com")
    assert "меньше двух" in str(exc_info.value)


def test_parse_gpx_ignores_points_without_time_in_distance_calc():
    # Средняя точка без <time> должна выпасть из расчёта: расстояние считается
    # только между первой и последней (timed) точками, а не через среднюю.
    content = _build_gpx(
        [
            (45.0000000, 0.0, 100, "2026-08-01T10:00:00Z", None),
            (46.0000000, 0.0, 100, None, None),  # без времени — исключается
            (45.0009000, 0.0, 100, "2026-08-01T10:00:10Z", None),
        ]
    )
    workouts = parse_gpx(content, "user@example.com")
    expected_distance = _haversine_km_reference(45.0, 0.0, 45.0009, 0.0)
    assert workouts[0].distance_km == pytest.approx(expected_distance)


def test_parse_gpx_avg_speed_none_when_every_gap_is_a_pause():
    content = _build_gpx(
        [
            (45.0000000, 0.0, 100, "2026-08-01T10:00:00Z", None),
            (45.0009000, 0.0, 100, "2026-08-01T10:01:00Z", None),  # 60с > 30с
        ]
    )
    workouts = parse_gpx(content, "user@example.com")
    assert workouts[0].avg_speed_kmh is None
    assert workouts[0].distance_km > 0


def test_parse_gpx_elevation_gain_none_when_no_elevation_data():
    content = _build_gpx(
        [
            (45.0000000, 0.0, None, "2026-08-01T10:00:00Z", None),
            (45.0009000, 0.0, None, "2026-08-01T10:00:10Z", None),
        ]
    )
    workouts = parse_gpx(content, "user@example.com")
    assert workouts[0].elevation_gain_m is None


def test_parse_gpx_elevation_gain_without_smoothing_for_two_points():
    # 2 точки < ELEVATION_SMOOTHING_WINDOW(3) -> сглаживание не применяется,
    # gain = просто прирост между двумя значениями.
    content = _build_gpx(
        [
            (45.0000000, 0.0, 100, "2026-08-01T10:00:00Z", None),
            (45.0009000, 0.0, 130, "2026-08-01T10:00:10Z", None),
        ]
    )
    workouts = parse_gpx(content, "user@example.com")
    assert workouts[0].elevation_gain_m == pytest.approx(30.0)


def test_parse_gpx_avg_hr_none_when_no_hr_extension():
    content = _build_gpx(
        [
            (45.0000000, 0.0, 100, "2026-08-01T10:00:00Z", None),
            (45.0009000, 0.0, 100, "2026-08-01T10:00:10Z", None),
        ]
    )
    workouts = parse_gpx(content, "user@example.com")
    assert workouts[0].avg_hr is None


def test_parse_gpx_extracts_hr_from_plain_hr_tag_without_namespace():
    content = _build_gpx(
        [
            (45.0000000, 0.0, 100, "2026-08-01T10:00:00Z", 110),
            (45.0009000, 0.0, 100, "2026-08-01T10:00:10Z", 120),
        ],
        hr_style="plain",
    )
    workouts = parse_gpx(content, "user@example.com")
    assert workouts[0].avg_hr == pytest.approx(115.0)


# =====================================================================
# FIT (через мок fitparse.FitFile)
# =====================================================================


class FakeFitMessage:
    def __init__(self, name, fields):
        self.name = name
        self._fields = fields

    def get_value(self, key):
        return self._fields.get(key)


class FakeFitFile:
    def __init__(self, messages):
        self._messages = messages

    def __call__(self, *_args, **_kwargs):
        return self

    def get_messages(self):
        return self._messages


def _patch_fit_messages(monkeypatch, messages):
    import app.parser as parser_module

    fake = FakeFitFile(messages)
    monkeypatch.setattr(parser_module.fitparse, "FitFile", fake)


def test_parse_fit_uses_session_message_when_present(monkeypatch):
    session_msg = FakeFitMessage(
        "session",
        {
            "total_distance": 15000.0,  # м
            "total_timer_time": 3600.0,  # с
            "start_time": datetime.datetime(2026, 8, 1, 10, 0, 0),
            "avg_speed": 4.5,  # м/с
            "avg_heart_rate": 140,
            "total_ascent": 120,
        },
    )
    _patch_fit_messages(monkeypatch, [session_msg])

    workouts = parse_fit(b"ignored", "user@example.com")

    assert len(workouts) == 1
    w = workouts[0]
    assert w.date == "2026-08-01"
    assert w.distance_km == pytest.approx(15.0)
    assert w.duration_min == pytest.approx(60.0)
    assert w.avg_speed_kmh == pytest.approx(4.5 * 3.6)
    assert w.avg_hr == 140
    assert w.elevation_gain_m == 120
    assert w.source == "fit"


def test_parse_fit_session_without_avg_speed_computes_from_distance_and_time(monkeypatch):
    session_msg = FakeFitMessage(
        "session",
        {
            "total_distance": 10000.0,
            "total_timer_time": 3600.0,
            "start_time": datetime.datetime(2026, 8, 1, 10, 0, 0),
        },
    )
    _patch_fit_messages(monkeypatch, [session_msg])

    workouts = parse_fit(b"ignored", "user@example.com")
    # 10 км за 1 час -> 10 км/ч
    assert workouts[0].avg_speed_kmh == pytest.approx(10.0)


def test_parse_fit_session_missing_total_distance_raises(monkeypatch):
    session_msg = FakeFitMessage(
        "session",
        {
            "total_timer_time": 3600.0,
            "start_time": datetime.datetime(2026, 8, 1, 10, 0, 0),
        },
    )
    _patch_fit_messages(monkeypatch, [session_msg])

    with pytest.raises(FitParseError):
        parse_fit(b"ignored", "user@example.com")


def test_parse_fit_session_missing_start_time_raises(monkeypatch):
    session_msg = FakeFitMessage(
        "session",
        {
            "total_distance": 1000.0,
            "total_timer_time": 60.0,
        },
    )
    _patch_fit_messages(monkeypatch, [session_msg])

    with pytest.raises(FitParseError):
        parse_fit(b"ignored", "user@example.com")


def test_parse_fit_falls_back_to_records_with_distance_field(monkeypatch):
    t0 = datetime.datetime(2026, 8, 1, 10, 0, 0)
    records = [
        FakeFitMessage(
            "record",
            {"timestamp": t0, "distance": 0.0, "heart_rate": 120, "altitude": 100.0},
        ),
        FakeFitMessage(
            "record",
            {
                "timestamp": t0 + datetime.timedelta(minutes=10),
                "distance": 3000.0,
                "heart_rate": 140,
                "altitude": 110.0,
            },
        ),
        FakeFitMessage(
            "record",
            {
                "timestamp": t0 + datetime.timedelta(minutes=20),
                "distance": 5000.0,
                "heart_rate": 150,
                "altitude": 105.0,
            },
        ),
    ]
    _patch_fit_messages(monkeypatch, records)

    workouts = parse_fit(b"ignored", "user@example.com")

    assert len(workouts) == 1
    w = workouts[0]
    assert w.distance_km == pytest.approx(5.0)  # последнее значение distance
    assert w.duration_min == pytest.approx(20.0)
    assert w.avg_speed_kmh == pytest.approx(5.0 / (20.0 / 60.0))
    assert w.avg_hr == pytest.approx((120 + 140 + 150) / 3)
    # raw gain (без сглаживания): 100->110 (+10), 110->105 (0) = 10
    assert w.elevation_gain_m == pytest.approx(10.0)
    assert w.date == "2026-08-01"
    assert w.source == "fit"


def test_parse_fit_falls_back_to_records_using_positions_when_no_distance(monkeypatch):
    def to_semicircles(deg):
        return int(deg * (2 ** 31) / 180.0)

    t0 = datetime.datetime(2026, 8, 1, 10, 0, 0)
    lat0, lat1 = 45.0, 45.001
    records = [
        FakeFitMessage(
            "record",
            {
                "timestamp": t0,
                "position_lat": to_semicircles(lat0),
                "position_long": to_semicircles(0.0),
            },
        ),
        FakeFitMessage(
            "record",
            {
                "timestamp": t0 + datetime.timedelta(minutes=5),
                "position_lat": to_semicircles(lat1),
                "position_long": to_semicircles(0.0),
            },
        ),
    ]
    _patch_fit_messages(monkeypatch, records)

    workouts = parse_fit(b"ignored", "user@example.com")

    expected_distance = _haversine_km_reference(lat0, 0.0, lat1, 0.0)
    assert workouts[0].distance_km == pytest.approx(expected_distance, rel=1e-3)


def test_parse_fit_raises_when_no_session_or_record_messages(monkeypatch):
    _patch_fit_messages(monkeypatch, [FakeFitMessage("device_info", {})])

    with pytest.raises(FitParseError) as exc_info:
        parse_fit(b"ignored", "user@example.com")
    assert "session/record" in str(exc_info.value)


def test_parse_fit_raises_when_records_have_no_timestamp(monkeypatch):
    records = [FakeFitMessage("record", {"distance": 100.0})]
    _patch_fit_messages(monkeypatch, records)

    with pytest.raises(FitParseError) as exc_info:
        parse_fit(b"ignored", "user@example.com")
    assert "timestamp" in str(exc_info.value)


def test_parse_fit_raises_when_no_distance_or_positions(monkeypatch):
    records = [FakeFitMessage("record", {"timestamp": datetime.datetime(2026, 8, 1)})]
    _patch_fit_messages(monkeypatch, records)

    with pytest.raises(FitParseError) as exc_info:
        parse_fit(b"ignored", "user@example.com")
    assert "distance" in str(exc_info.value)


def test_parse_fit_wraps_constructor_error_as_fitparseerror(monkeypatch):
    import app.parser as parser_module

    def boom(*_args, **_kwargs):
        raise ValueError("corrupt binary")

    monkeypatch.setattr(parser_module.fitparse, "FitFile", boom)

    with pytest.raises(FitParseError):
        parse_fit(b"garbage", "user@example.com")


# =====================================================================
# detect_file_type / parse_file (диспетчер)
# =====================================================================


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("workout.csv", "csv"),
        ("workout.gpx", "gpx"),
        ("workout.fit", "fit"),
        ("WORKOUT.GPX", "gpx"),
        ("Track.FIT", "fit"),
    ],
)
def test_detect_file_type_by_extension(filename, expected):
    assert detect_file_type(filename, b"irrelevant content") == expected


def test_detect_file_type_sniffs_gpx_xml_declaration_without_extension():
    content = b'<?xml version="1.0"?><gpx></gpx>'
    assert detect_file_type("noext", content) == "gpx"


def test_detect_file_type_sniffs_gpx_tag_without_xml_declaration():
    content = b"<gpx version=\"1.1\"></gpx>"
    assert detect_file_type("noext", content) == "gpx"


def test_detect_file_type_sniffs_fit_binary_signature():
    # Байты 8-12 в FIT-заголовке содержат магическую строку ".FIT"
    header = b"\x0e\x10" + b"\x00" * 6 + b".FIT" + b"\x00" * 4
    assert detect_file_type("noext", header) == "fit"


def test_detect_file_type_falls_back_to_csv_for_plain_text():
    content = b"date,distance_km,duration_min\n2026-01-01,10,30\n"
    assert detect_file_type("noext", content) == "csv"


def test_detect_file_type_empty_filename_and_content_falls_back_to_csv():
    assert detect_file_type("", b"") == "csv"


def test_parse_file_dispatches_to_gpx_parser():
    workouts = parse_file("track.gpx", read_sample_gpx_bytes(), "user@example.com")
    assert workouts[0].source == "gpx"


def test_parse_file_dispatches_to_fit_parser(monkeypatch):
    session_msg = FakeFitMessage(
        "session",
        {
            "total_distance": 1000.0,
            "total_timer_time": 600.0,
            "start_time": datetime.datetime(2026, 8, 1, 10, 0, 0),
        },
    )
    _patch_fit_messages(monkeypatch, [session_msg])

    workouts = parse_file("track.fit", b"ignored", "user@example.com")
    assert workouts[0].source == "fit"


def test_parse_file_dispatches_to_csv_parser():
    content = read_sample().encode("utf-8")
    workouts = parse_file("workouts.csv", content, "user@example.com")
    assert len(workouts) == 10
    assert workouts[0].source == "csv"


def test_parse_file_non_utf8_csv_raises_clear_error():
    content = b"date,distance_km,duration_min\n2026-01-01,10,30\n\xff\xfe"
    with pytest.raises(CsvParseError) as exc_info:
        parse_file("bad.csv", content, "user@example.com")
    assert "UTF-8" in str(exc_info.value)
