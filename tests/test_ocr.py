"""Тесты для app.ocr: автоопределение бэкенда и распознавание текста.

Реальный macOS Vision и бинарник tesseract НИКОГДА не вызываются — оба
бэкенда подменяются через monkeypatch (sys.modules для pyobjc-пакетов,
shutil.which для tesseract, и точечные моки внутренних функций модуля).
"""
import io
import sys
import types
from unittest.mock import MagicMock

import pytest

import app.ocr as ocr


# =====================================================================
# Хелперы: фиктивные pyobjc-модули для Vision
# =====================================================================


def _install_fake_vision_modules(monkeypatch, lines):
    """Подставляет в sys.modules фиктивные Quartz/Vision/Foundation, достаточные
    для успешного импорта (_vision_available) и для полного прохода
    _recognize_with_vision без реального macOS API."""
    foundation = types.ModuleType("Foundation")
    foundation.NSData = MagicMock()
    foundation.NSData.dataWithBytes_length_.return_value = MagicMock(name="nsdata")

    quartz = types.ModuleType("Quartz")
    quartz.CGImageSourceCreateWithData = MagicMock(return_value=MagicMock(name="source"))
    quartz.CGImageSourceCreateImageAtIndex = MagicMock(return_value=MagicMock(name="cgimage"))

    vision = types.ModuleType("Vision")
    vision.VNRequestTextRecognitionLevelAccurate = 1

    observations = []
    for line in lines:
        candidate = MagicMock()
        candidate.string.return_value = line
        observation = MagicMock()
        observation.topCandidates_.return_value = [candidate]
        observations.append(observation)

    request = MagicMock()
    request.results.return_value = observations
    vision.VNRecognizeTextRequest = MagicMock()
    vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = request

    handler_instance = MagicMock()
    handler_instance.performRequests_error_.return_value = (True, None)
    vision.VNImageRequestHandler = MagicMock()
    vision.VNImageRequestHandler.alloc.return_value.initWithCGImage_options_.return_value = (
        handler_instance
    )

    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setitem(sys.modules, "Vision", vision)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    return request, handler_instance


def _make_vision_unavailable(monkeypatch):
    """import Quartz / import Vision поднимут ImportError (None в sys.modules)."""
    monkeypatch.setitem(sys.modules, "Quartz", None)
    monkeypatch.setitem(sys.modules, "Vision", None)


def _make_tesseract_available(monkeypatch, path="/usr/local/bin/tesseract"):
    monkeypatch.setattr(ocr.shutil, "which", lambda name: path if name == "tesseract" else None)


def _make_tesseract_unavailable(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)


def _sample_jpeg_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (5, 5), color=(1, 2, 3)).save(buf, format="JPEG")
    return buf.getvalue()


# =====================================================================
# detect_backend: автоопределение
# =====================================================================


def test_detect_backend_prefers_vision_when_available(monkeypatch):
    _install_fake_vision_modules(monkeypatch, ["irrelevant"])
    _make_tesseract_available(monkeypatch)  # даже если tesseract тоже есть — vision в приоритете
    assert ocr.detect_backend() == "vision"


def test_detect_backend_falls_back_to_tesseract_when_vision_unavailable(monkeypatch):
    _make_vision_unavailable(monkeypatch)
    _make_tesseract_available(monkeypatch)
    assert ocr.detect_backend() == "tesseract"


def test_detect_backend_returns_none_when_nothing_available(monkeypatch):
    _make_vision_unavailable(monkeypatch)
    _make_tesseract_unavailable(monkeypatch)
    assert ocr.detect_backend() == "none"


def test_tesseract_availability_checked_by_binary_name(monkeypatch):
    calls = []

    def fake_which(name):
        calls.append(name)
        return None

    monkeypatch.setattr(ocr.shutil, "which", fake_which)
    _make_vision_unavailable(monkeypatch)
    assert ocr.detect_backend() == "none"
    assert "tesseract" in calls


# =====================================================================
# recognize_text: путь "нет OCR"
# =====================================================================


def test_recognize_text_with_no_backend_returns_hint_message(monkeypatch):
    result = ocr.recognize_text(b"irrelevant-bytes", backend="none")
    assert result["text"] == ""
    assert result["backend"] == "none"
    assert result["message"] == ocr.NO_OCR_MESSAGE
    assert result["message"]  # подсказка непустая


def test_recognize_text_autodetects_none_when_both_backends_missing(monkeypatch):
    _make_vision_unavailable(monkeypatch)
    _make_tesseract_unavailable(monkeypatch)
    result = ocr.recognize_text(b"irrelevant-bytes")
    assert result["backend"] == "none"
    assert result["text"] == ""
    assert "Vision" in result["message"] or "tesseract" in result["message"].lower() or "Tesseract" in result["message"]


# =====================================================================
# recognize_text: бэкенд vision (полностью замокан)
# =====================================================================


def test_recognize_text_with_vision_backend_joins_recognized_lines(monkeypatch):
    _install_fake_vision_modules(monkeypatch, ["Distance 42.15 km", "1:42:07"])
    result = ocr.recognize_text(b"fake-image-bytes", backend="vision")
    assert result["backend"] == "vision"
    assert result["message"] is None
    assert result["text"] == "Distance 42.15 km\n1:42:07"


def test_recognize_text_with_vision_backend_handles_empty_results(monkeypatch):
    _install_fake_vision_modules(monkeypatch, [])
    result = ocr.recognize_text(b"fake-image-bytes", backend="vision")
    assert result["text"] == ""
    assert result["backend"] == "vision"


def test_recognize_with_vision_raises_ocr_error_on_undecodable_image(monkeypatch):
    _install_fake_vision_modules(monkeypatch, ["irrelevant"])
    import Quartz  # заглушка, установленная выше

    Quartz.CGImageSourceCreateWithData.return_value = None
    with pytest.raises(ocr.OcrError):
        ocr.recognize_text(b"not-really-an-image", backend="vision")


# =====================================================================
# recognize_text: бэкенд tesseract (image_to_string замокан — реальный
# бинарник tesseract не вызывается)
# =====================================================================


def test_recognize_text_with_tesseract_backend_returns_mocked_text(monkeypatch):
    pytesseract = pytest.importorskip("pytesseract")
    monkeypatch.setattr(pytesseract, "image_to_string", lambda image, lang=None: "Дистанция: 42,15 км")

    result = ocr.recognize_text(_sample_jpeg_bytes(), backend="tesseract")
    assert result["backend"] == "tesseract"
    assert result["message"] is None
    assert result["text"] == "Дистанция: 42,15 км"


def test_recognize_text_with_tesseract_backend_passes_expected_languages(monkeypatch):
    pytesseract = pytest.importorskip("pytesseract")
    captured = {}

    def fake_image_to_string(image, lang=None):
        captured["lang"] = lang
        return ""

    monkeypatch.setattr(pytesseract, "image_to_string", fake_image_to_string)
    ocr.recognize_text(_sample_jpeg_bytes(), backend="tesseract")
    assert captured["lang"] == "rus+eng"


# =====================================================================
# Явный backend имеет приоритет над автоопределением
# =====================================================================


def test_explicit_backend_overrides_autodetection(monkeypatch):
    # Vision доступен, но явно просим 'none' — не должно быть вызова Vision.
    _install_fake_vision_modules(monkeypatch, ["should not be used"])
    result = ocr.recognize_text(b"irrelevant", backend="none")
    assert result["backend"] == "none"
    assert result["text"] == ""
