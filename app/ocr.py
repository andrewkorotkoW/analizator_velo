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


def _vision_available() -> bool:
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def detect_backend() -> str:
    """Определяет доступный бэкенд: 'vision', 'tesseract' или 'none'."""
    if _vision_available():
        return "vision"
    if _tesseract_available():
        return "tesseract"
    return "none"


def _recognize_with_vision(image_bytes: bytes) -> str:
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
    request.setRecognitionLanguages_(["ru-RU", "en-US"])
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
        return {"text": _recognize_with_vision(image_bytes), "backend": "vision", "message": None}
    if backend == "tesseract":
        return {"text": _recognize_with_tesseract(image_bytes), "backend": "tesseract", "message": None}

    return {"text": "", "backend": "none", "message": NO_OCR_MESSAGE}
