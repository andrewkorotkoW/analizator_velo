"""Тесты для app.photo_parse.parse_ocr_text: разбор текста OCR с фото тренировки.

Табличные случаи на реальных форматах экранов Garmin/Wahoo/Strava (RU/EN).
Отдельно проверяем, что двусмысленные/нераспознаваемые фрагменты остаются
None, а не додумываются.
"""
import pytest

from app.photo_parse import FIELDS, parse_ocr_text

# =====================================================================
# Позитивные случаи: одно поле на фрагмент экрана (Garmin/Wahoo/Strava RU+EN)
# =====================================================================

SINGLE_FIELD_CASES = [
    # (текст OCR, поле, ожидаемое значение)
    pytest.param("Distance 42.15 km", "distance_km", 42.15, id="garmin_distance_en"),
    pytest.param("1:42:07", "duration_min", 102 + 7 / 60.0, id="garmin_duration_hms"),
    pytest.param("Дистанция: 42,15 км", "distance_km", 42.15, id="strava_distance_ru_comma"),
    pytest.param("Ср. пульс 142 уд/мин", "avg_hr", 142.0, id="strava_avg_hr_ru"),
    pytest.param("1 ч 42 мин", "duration_min", 102.0, id="strava_duration_ru_words"),
    pytest.param("Набор высоты 512 м", "elevation_gain_m", 512.0, id="strava_elevation_ru_label_first"),
    pytest.param("Elevation Gain 512 m", "elevation_gain_m", 512.0, id="wahoo_elevation_en_label_first"),
    pytest.param("512 m Elevation Gain", "elevation_gain_m", 512.0, id="wahoo_elevation_en_number_first"),
    pytest.param("28.5 km/h", "avg_speed_kmh", 28.5, id="garmin_speed_en"),
    pytest.param("142 bpm", "avg_hr", 142.0, id="garmin_hr_bpm"),
    pytest.param("142уд/мин", "avg_hr", 142.0, id="hr_ru_no_spaces"),
    pytest.param("142 уд. мин", "avg_hr", 142.0, id="hr_ru_dot_variant"),
    pytest.param("2026-09-15", "date", "2026-09-15", id="date_iso"),
    pytest.param("15.09.2026", "date", "2026-09-15", id="date_dmy_dot"),
    pytest.param("15 сентября 2026", "date", "2026-09-15", id="date_ru_words"),
    pytest.param("1ч42мин", "duration_min", 102.0, id="duration_ru_words_no_spaces"),
]


@pytest.mark.parametrize("text, field, expected", SINGLE_FIELD_CASES)
def test_recognized_field_extracted_with_expected_value(text, field, expected):
    result = parse_ocr_text(text)
    actual = result[field]
    if isinstance(expected, float):
        assert actual == pytest.approx(expected)
    else:
        assert actual == expected
    assert field in result["fragments"]
    assert result["fragments"][field]  # непустой сырой фрагмент


def test_recognized_field_reports_nonzero_confidence():
    result = parse_ocr_text("Distance 42.15 km")
    assert result["confidence"] > 0


# =====================================================================
# Комбинированный "экран сводки" — несколько полей сразу
# =====================================================================


def test_full_summary_screen_extracts_all_fields():
    text = (
        "Time 1:42:07 Distance 42.15km Avg HR 142bpm Elev Gain 512m"
    )
    result = parse_ocr_text(text)
    assert result["distance_km"] == pytest.approx(42.15)
    assert result["duration_min"] == pytest.approx(102.11666666666666)
    assert result["avg_hr"] == pytest.approx(142.0)
    assert result["elevation_gain_m"] == pytest.approx(512.0)
    # На этом экране нет даты и скорости — додумывать их нельзя
    assert result["date"] is None
    assert result["avg_speed_kmh"] is None
    assert result["confidence"] == pytest.approx(4 / len(FIELDS), abs=0.01)


def test_russian_full_summary_screen_extracts_all_fields():
    text = "Дистанция: 42,15 км\nСр. пульс 142 уд/мин\n1 ч 42 мин\nНабор высоты 512 м"
    result = parse_ocr_text(text)
    assert result["distance_km"] == pytest.approx(42.15)
    assert result["avg_hr"] == pytest.approx(142.0)
    assert result["duration_min"] == pytest.approx(102.0)
    assert result["elevation_gain_m"] == pytest.approx(512.0)


# =====================================================================
# Дистанция vs скорость: "42.15 km/h" не должно засчитаться как дистанция
# =====================================================================


def test_speed_fragment_is_not_mistaken_for_distance():
    result = parse_ocr_text("42.15 km/h")
    assert result["avg_speed_kmh"] == pytest.approx(42.15)
    assert result["distance_km"] is None


def test_distance_fragment_is_not_mistaken_for_speed():
    result = parse_ocr_text("Distance 42.15 km")
    assert result["distance_km"] == pytest.approx(42.15)
    assert result["avg_speed_kmh"] is None


# =====================================================================
# Двусмысленные / нераспознаваемые фрагменты — должны остаться None,
# а не быть додуманы
# =====================================================================


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty_string"),
        pytest.param("   ", id="whitespace_only"),
        pytest.param("42.15", id="bare_number_no_unit"),
        pytest.param("42", id="bare_integer_no_unit"),
        pytest.param("Дистанция 42.15", id="ru_label_without_unit"),
        pytest.param("Ascent 512m", id="unrecognized_elevation_label_ascent"),
        pytest.param("05.13.2026", id="invalid_month_13_rejected"),
        pytest.param("garbage OCR n0i$e ###", id="pure_noise"),
    ],
)
def test_ambiguous_or_unrecognizable_fragment_stays_none_for_all_fields(text):
    result = parse_ocr_text(text)
    for field in FIELDS:
        assert result[field] is None, f"{field} should stay None for input {text!r}"
    assert result["fragments"] == {}
    assert result["confidence"] == 0.0


def test_none_input_does_not_raise_and_returns_all_none():
    result = parse_ocr_text(None)
    for field in FIELDS:
        assert result[field] is None
    assert result["confidence"] == 0.0


# =====================================================================
# Дефект: _valid_date не проверяет реальное количество дней в месяце —
# "31 февраля" и "30 февраля" принимаются как валидные даты.
# Тест документирует текущее (ошибочное) поведение; см. отчёт о дефектах.
# =====================================================================


@pytest.mark.xfail(reason="дефект: _valid_date не проверяет число дней в месяце (31.02 принимается)", strict=True)
@pytest.mark.parametrize(
    "text",
    [
        pytest.param("31.02.2026", id="february_31st_dmy"),
        pytest.param("30 фев 2026", id="february_30th_words"),
    ],
)
def test_calendar_invalid_date_is_rejected(text):
    result = parse_ocr_text(text)
    assert result["date"] is None


# =====================================================================
# Транслит: на macOS < 13 Vision не поддерживает ru-RU, и русский текст
# распознаётся похожими по начертанию латинскими буквами/цифрами (см.
# app.ocr.RUSSIAN_NOT_SUPPORTED_MESSAGE). normalize_transliteration()
# должна вернуть все поля из такого текста, как если бы он был на обычной
# кириллице.
# =====================================================================


def test_full_translit_vision_summary_screen_extracts_all_six_fields():
    """Реальный вывод Vision для экрана с итогами заезда на macOS без
    поддержки русского: кириллица заменена похожими латинскими буквами и
    цифрами (PacctoAHMe=Расстояние, KM/4=км/ч, yA/MUH=уд/мин, Ha6op
    BbICoTbl=Набор высоты, CeHTA6pa=сентября)."""
    text = (
        "Утренний заезд / 17 CeHTA6pa 2026 / PacctoAHMe / 42,3 KM / "
        "Время в движении / 1:38:20 / Cpeдняя Ckopoctb / 25,8 KM/4 / "
        "Средний nymbe / 146 yA/MUH / Ha6op BbICoTbl / 410 M"
    )
    result = parse_ocr_text(text)
    assert result["date"] == "2026-09-17"
    assert result["distance_km"] == pytest.approx(42.3)
    assert result["duration_min"] == pytest.approx(98.33333333333333)
    assert result["avg_speed_kmh"] == pytest.approx(25.8)
    assert result["avg_hr"] == pytest.approx(146.0)
    assert result["elevation_gain_m"] == pytest.approx(410.0)
    assert result["confidence"] == 1.0


def test_translit_speed_unit_km_slash_4_normalized_to_km_h():
    result = parse_ocr_text("25,8 KM/4")
    assert result["avg_speed_kmh"] == pytest.approx(25.8)
    assert result["distance_km"] is None


def test_translit_hr_unit_yA_MUH_normalized_to_bpm():
    result = parse_ocr_text("146 yA/MUH")
    assert result["avg_hr"] == pytest.approx(146.0)


def test_translit_hr_unit_mixed_latin_y_cyrillic_normalized_to_bpm():
    result = parse_ocr_text("146 yд/мин")
    assert result["avg_hr"] == pytest.approx(146.0)


def test_translit_elevation_label_Ha6op_BbICoTbl_recognized():
    result = parse_ocr_text("Ha6op BbICoTbl 410 m")
    assert result["elevation_gain_m"] == pytest.approx(410.0)


def test_translit_month_recognized_for_other_months_when_evidenced_letters_match():
    # Все буквы в "марта"/"августа" (м,а,р,т/а,в,г,у,с,т,а) входят в таблицу
    # соответствий, поэтому и другие месяцы, не только сентябрь, распознаются.
    result = parse_ocr_text("5 Mapta 2026")
    assert result["date"] == "2026-03-05"


def test_translit_normalization_does_not_affect_clean_cyrillic_text():
    text = "Дистанция: 42,3 км\nСредняя скорость: 25,8 км/ч\nСредний пульс: 146 уд/мин\nНабор высоты: 410 м\n17 сентября 2026"
    result = parse_ocr_text(text)
    assert result["distance_km"] == pytest.approx(42.3)
    assert result["avg_speed_kmh"] == pytest.approx(25.8)
    assert result["avg_hr"] == pytest.approx(146.0)
    assert result["elevation_gain_m"] == pytest.approx(410.0)
    assert result["date"] == "2026-09-17"


# =====================================================================
# Разбор «подпись — значение на соседней строке» (типичная раскладка
# экранов велокомпьютеров: заголовок, затем число без единицы измерения
# рядом). Значение+единица на одной строке остаются приоритетным путём —
# фолбэк применяется только для строк, где число нашлось не на этой же
# строке, что подпись.
# =====================================================================


def test_garmin_wahoo_style_label_then_bare_value_on_next_line():
    text = (
        "Distance\n42.3\nAvg Speed\n25.8 km/h\nAvg HR\n142\n"
        "Elevation Gain\n410 m\nTime\n1:38:20\nDate\n17.09.2026"
    )
    result = parse_ocr_text(text)
    assert result["distance_km"] == pytest.approx(42.3)
    assert result["avg_speed_kmh"] == pytest.approx(25.8)
    assert result["avg_hr"] == pytest.approx(142.0)
    assert result["elevation_gain_m"] == pytest.approx(410.0)
    assert result["duration_min"] == pytest.approx(98.33333333333333)
    assert result["date"] == "2026-09-17"
    assert result["confidence"] == 1.0


def test_label_then_bare_value_fallback_does_not_override_same_line_ambiguous_case():
    # Регрессия для test_ambiguous_or_unrecognizable_fragment_stays_none_for_all_fields:
    # подпись и число на ОДНОЙ строке без единицы измерения по-прежнему
    # остаются недостоверными — додумывать нельзя, даже если рядом есть подпись.
    result = parse_ocr_text("Дистанция 42.15")
    assert result["distance_km"] is None


def test_wahoo_style_all_fields_on_same_line_with_units_still_works():
    text = (
        "Ride Distance: 42.3 km | Elevation Gain: 410m | Avg Heart Rate: 142 bpm | "
        "Avg Speed: 25.8km/h | Moving Time: 1:38:20"
    )
    result = parse_ocr_text(text)
    assert result["distance_km"] == pytest.approx(42.3)
    assert result["elevation_gain_m"] == pytest.approx(410.0)
    assert result["avg_hr"] == pytest.approx(142.0)
    assert result["avg_speed_kmh"] == pytest.approx(25.8)
    assert result["duration_min"] == pytest.approx(98.33333333333333)


def test_strava_style_russian_screen_via_tesseract_clean_cyrillic():
    # Strava-скрин через tesseract: кириллица уже нормальная, транслит не нужен.
    text = (
        "Утренний заезд\n17 сентября 2026\nРасстояние\n42,3 км\n"
        "Время в движении\n1:38:20\nСредняя скорость\n25,8 км/ч\n"
        "Средний пульс\n146 уд/мин\nНабор высоты\n410 м"
    )
    result = parse_ocr_text(text)
    assert result["date"] == "2026-09-17"
    assert result["distance_km"] == pytest.approx(42.3)
    assert result["duration_min"] == pytest.approx(98.33333333333333)
    assert result["avg_speed_kmh"] == pytest.approx(25.8)
    assert result["avg_hr"] == pytest.approx(146.0)
    assert result["elevation_gain_m"] == pytest.approx(410.0)
    assert result["confidence"] == 1.0
