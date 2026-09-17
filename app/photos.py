"""Хранение фото тренировок: валидация, ресайз, временное и постоянное хранилище.

Поток: save_temp_photo() кладёт обработанное фото во временную папку и
возвращает token; после подтверждения пользователем finalize_photo()
переносит его в постоянное место workspace/photos/<user_id>/<token>.jpg
и возвращает относительный путь для сохранения в БД.
"""
import io
import os
import re
import uuid
from typing import Optional, Tuple

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_DIMENSION = 1600
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "heif"}

PHOTOS_ROOT = os.environ.get(
    "ANAL_VELO_PHOTOS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace", "photos"),
)

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_PERMANENT_RELPATH_RE = re.compile(r"^(?P<user_id>\d+)/(?P<token>[0-9a-f]{32})\.jpg$")


def _tmp_dir() -> str:
    """Вычисляется заново при каждом вызове, чтобы тесты могли подменить PHOTOS_ROOT."""
    return os.path.join(PHOTOS_ROOT, "tmp")


class PhotoError(ValueError):
    """Ошибка обработки или хранения фото тренировки."""


def _ensure_heif_support() -> None:
    try:
        import pillow_heif
    except ImportError as exc:
        raise PhotoError(
            "HEIC не поддерживается: установите pillow-heif (pip install pillow-heif)"
        ) from exc
    pillow_heif.register_heif_opener()


def _detect_extension(filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    if ext in ALLOWED_EXTENSIONS:
        return ext

    if content[:3] == b"\xff\xd8\xff":
        return "jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if content[4:8] == b"ftyp":
        return "heic"

    raise PhotoError("Неподдерживаемый формат фото: используйте JPG, PNG или HEIC")


def _load_image(content: bytes, ext: str) -> Image.Image:
    if ext in ("heic", "heif"):
        _ensure_heif_support()
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception as exc:
        raise PhotoError(f"Не удалось открыть изображение: {exc}") from exc
    return image


def process_photo(content: bytes, filename: str) -> bytes:
    """Валидирует размер/формат, поворачивает по EXIF, ресайзит. Возвращает JPEG-байты."""
    if not content:
        raise PhotoError("Пустой файл")
    if len(content) > MAX_UPLOAD_BYTES:
        raise PhotoError("Файл слишком большой: максимум 15 МБ")

    ext = _detect_extension(filename, content)
    image = _load_image(content, ext)

    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    width, height = image.size
    largest = max(width, height)
    if largest > MAX_DIMENSION:
        scale = MAX_DIMENSION / largest
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _validate_token(token: str) -> str:
    if not token or not _TOKEN_RE.match(token):
        raise PhotoError("Некорректный идентификатор фото")
    return token


def save_temp_photo(content: bytes, filename: str) -> str:
    """Обрабатывает и сохраняет фото во временное хранилище. Возвращает token."""
    processed = process_photo(content, filename)
    tmp_dir = _tmp_dir()
    os.makedirs(tmp_dir, exist_ok=True)
    token = uuid.uuid4().hex
    with open(os.path.join(tmp_dir, f"{token}.jpg"), "wb") as f:
        f.write(processed)
    return token


def temp_photo_path(token: str) -> Optional[str]:
    """Путь к временному фото по token, либо None, если не найдено."""
    try:
        token = _validate_token(token)
    except PhotoError:
        return None
    path = os.path.join(_tmp_dir(), f"{token}.jpg")
    return path if os.path.isfile(path) else None


def finalize_photo(token: str, user_id: int) -> str:
    """Переносит временное фото в постоянное хранилище пользователя.

    Возвращает относительный путь (<user_id>/<token>.jpg) для сохранения в БД.
    """
    token = _validate_token(token)
    tmp_path = os.path.join(_tmp_dir(), f"{token}.jpg")
    if not os.path.isfile(tmp_path):
        raise PhotoError("Фото не найдено или уже подтверждено — загрузите заново")

    user_dir = os.path.join(PHOTOS_ROOT, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    dest_path = os.path.join(user_dir, f"{token}.jpg")
    os.replace(tmp_path, dest_path)
    return f"{user_id}/{token}.jpg"


def resolve_permanent_photo(relative_path: str) -> Optional[Tuple[int, str]]:
    """Проверяет relative_path (как хранится в photo_path) и возвращает (owner_id, полный путь).

    Возвращает None, если формат некорректен или файл не найден — защищает от
    обхода пути (path traversal), так как принимает только строго проверенный формат.
    """
    match = _PERMANENT_RELPATH_RE.match(relative_path or "")
    if not match:
        return None
    owner_id = int(match.group("user_id"))
    path = os.path.join(PHOTOS_ROOT, str(owner_id), f"{match.group('token')}.jpg")
    if not os.path.isfile(path):
        return None
    return owner_id, path
