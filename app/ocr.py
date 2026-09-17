"""OCR-бэкенды для распознавания текста на фото тренировки.

Бэкенд определяется автоматически (detect_backend): на macOS — системный
Vision (через pyobjc), иначе — Tesseract, если бинарник найден в PATH.
Если ничего не доступно — возвращается пустой текст с понятным сообщением.

recognize_text принимает необязательный параметр backend, чтобы его можно
было подменить в тестах, не вызывая реальный Vision/tesseract.
"""
import io
import shutil
from typing import Optional, TypedDict


class OcrResult(TypedDict):
    text: str
    backend: str
    message: Optional[str]


NO_OCR_MESSAGE = (
    "OCR недоступен: на macOS используется системный Vision (пакет pyobjc-framework-Vision), "
    "на других платформах установите Tesseract OCR (например, brew install tesseract "
    "tesseract-lang или apt install tesseract-ocr tesseract-ocr-rus) и pip install pytesseract."
)

RUSSIAN_NOT_SUPPORTED_MESSAGE = (
    "Русский не поддерживается этой версией macOS (Vision умеет только en, fr, it, de, es, "
    "pt, zh) — распознавание выполнено на английском и может быть неточным. Установите "
    "tesseract: brew install tesseract tesseract-lang"
)


def _vision_available() -> bool:
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def _vision_supports_russian() -> bool:
    """До macOS 13 VNRecognizeTextRequest не умеет распознавать русский —
    supportedRecognitionLanguagesAndReturnError_ на таких системах возвращает
    только en/fr/it/de/es/pt/zh, без 'ru-RU'."""
    import Vision

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    languages, error = request.supportedRecognitionLanguagesAndReturnError_(None)
    if error is not None or not languages:
        return False
    return "ru-RU" in list(languages)


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def detect_backend() -> str:
    """Определяет, каким бэкендом распознавать текст: 'vision', 'tesseract' или 'none'.

    Vision предпочитается, только если он умеет распознавать русский. Если нет
    (см. _vision_supports_russian), но доступен tesseract — предпочитаем его,
    так как он распознаёт русский на любой версии macOS. Если и tesseract нет —
    используем Vision на английском (recognize_text вернёт понятную подсказку).
    """
    vision_ok = _vision_available()
    if vision_ok and _vision_supports_russian():
        return "vision"
    if _tesseract_available():
        return "tesseract"
    if vision_ok:
        return "vision"
    return "none"


def _recognize_with_vision(image_bytes: bytes, languages) -> str:
    import Quartz
    import Vision
    from Foundation import NSData

    data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    if source is None:
        raise OcrError("Не удалось декодировать изображение для Vision")
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if cg_image is None:
        raise OcrError("Не удалось декодировать изображение для Vision")

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(list(languages))
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    success, error = handler.performRequests_error_([request], None)
    if not success:
        raise OcrError(f"Ошибка распознавания Vision: {error}")

    lines = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(str(candidates[0].string()))
    return "\n".join(lines)


def _recognize_with_tesseract(image_bytes: bytes) -> str:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(image, lang="rus+eng")


class OcrError(RuntimeError):
    """Ошибка распознавания текста выбранным OCR-бэкендом."""


def recognize_text(image_bytes: bytes, backend: Optional[str] = None) -> OcrResult:
    """Распознаёт текст на фото выбранным (или автоопределённым) бэкендом.

    backend можно передать явно ('vision'/'tesseract'/'none') — в частности,
    чтобы подменить реальное распознавание в тестах.
    """
    backend = backend or detect_backend()

    if backend == "vision":
        ru_supported = _vision_supports_russian()
        languages = ["ru-RU", "en-US"] if ru_supported else ["en-US"]
        text = _recognize_with_vision(image_bytes, languages)
        message = None if ru_supported else RUSSIAN_NOT_SUPPORTED_MESSAGE
        return {"text": text, "backend": "vision", "message": message}
    if backend == "tesseract":
        return {"text": _recognize_with_tesseract(image_bytes), "backend": "tesseract", "message": None}

    return {"text": "", "backend": "none", "message": NO_OCR_MESSAGE}
