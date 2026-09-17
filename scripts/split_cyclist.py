#!/usr/bin/env python3
"""
Разрезает app/static/img/loader/cyclist.png на три слоя для анимации лоадера:
wheel_rear.png, wheel_front.png (круглые вырезки колёс) и body.png (всё
остальное, с прозрачными "дырками" на месте колёс, чтобы вращающиеся колёса
не давали двойного контура под телом).

Запуск (один раз, после замены cyclist.png на свою иллюстрацию):
    .venv/bin/python scripts/split_cyclist.py

Ищет два самых тёмных круглых кластера пикселей в нижней трети изображения
(колёса). Если детекция ненадёжна (кластеры не найдены/не круглые/слишком
близко друг к другу), использует запасные координаты, подобранные под
исходную иллюстрацию 360×360.
"""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit(
        "Pillow не установлен. Установите его в окружение проекта:\n"
        "    .venv/bin/pip install Pillow\n"
        "и запустите скрипт снова: .venv/bin/python scripts/split_cyclist.py"
    )

SOURCE = Path(__file__).resolve().parent.parent / "app" / "static" / "img" / "loader" / "cyclist.png"
OUT_DIR = SOURCE.parent

# Запасные ориентиры на случай ненадёжной автодетекции (под исходную иллюстрацию).
FALLBACK_REAR = (78, 258)
FALLBACK_FRONT = (292, 258)
FALLBACK_RADIUS = 62

DARK_LUMA_THRESHOLD = 90  # пиксель — часть колеса, если светлота ниже порога
ALPHA_OPAQUE_THRESHOLD = 128
MIN_BLOB_PIXELS = 200  # отсекаем мелкий тёмный шум (тени, окантовки одежды)
WHEEL_MARGIN = 6  # запас по радиусу при вырезке колеса, чтобы не срезать антиалиасинг
HOLE_SHRINK = 4  # дырка в body.png на столько меньше радиуса колеса


def _luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def _find_dark_blobs(image):
    """BFS-кластеризация тёмных непрозрачных пикселей в нижней трети изображения."""
    w, h = image.size
    px = image.load()
    y_start = (2 * h) // 3
    visited = [[False] * w for _ in range(h)]

    def is_dark(x, y):
        r, g, b, a = px[x, y]
        return a >= ALPHA_OPAQUE_THRESHOLD and _luma(r, g, b) < DARK_LUMA_THRESHOLD

    blobs = []
    for y in range(y_start, h):
        for x in range(w):
            if visited[y][x] or not is_dark(x, y):
                continue
            stack = [(x, y)]
            visited[y][x] = True
            pixels = []
            while stack:
                cx, cy = stack.pop()
                pixels.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if (
                        0 <= nx < w
                        and y_start <= ny < h
                        and not visited[ny][nx]
                        and is_dark(nx, ny)
                    ):
                        visited[ny][nx] = True
                        stack.append((nx, ny))
            blobs.append(pixels)
    return blobs


def _blob_stats(pixels):
    xs = [p[0] for p in pixels]
    ys = [p[1] for p in pixels]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    area = len(pixels)
    r = (area / 3.14159265) ** 0.5
    bw = max(xs) - min(xs) + 1
    bh = max(ys) - min(ys) + 1
    return cx, cy, r, bw, bh


def detect_wheels(image):
    """Возвращает ((rear_x, rear_y), (front_x, front_y), radius) либо None, если
    автодетекция ненадёжна."""
    blobs = [b for b in _find_dark_blobs(image) if len(b) >= MIN_BLOB_PIXELS]
    if len(blobs) < 2:
        return None

    blobs.sort(key=len, reverse=True)
    candidates = blobs[:4]  # спицы/руки механика могут разорвать колесо на пару кластеров

    scored = []
    for b in candidates:
        cx, cy, r, bw, bh = _blob_stats(b)
        circularity = len(b) / (3.14159265 * r * r) if r > 0 else 0
        roundness = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 0
        scored.append((cx, cy, r, circularity, roundness))

    good = [s for s in scored if 25 <= s[2] <= 100 and s[4] >= 0.7 and 0.45 <= s[3] <= 1.3]
    if len(good) < 2:
        return None

    good.sort(key=lambda s: s[0])
    rear, front = good[0], good[-1]
    if front[0] - rear[0] < 100:
        return None

    radius = (rear[2] + front[2]) / 2
    return (rear[0], rear[1]), (front[0], front[1]), radius


def make_wheel_layer(image, center, radius):
    """Круглая вырезка колеса (с запасом WHEEL_MARGIN), остальное — прозрачно."""
    cx, cy = center
    r = radius + WHEEL_MARGIN
    size = int(round(2 * r))
    left = int(round(cx - r))
    top = int(round(cy - r))

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image.crop((left, top, left + size, top + size)), (0, 0))

    mask = Image.new("L", (size, size), 0)
    mpx = mask.load()
    r2 = r * r
    center_local = size / 2
    for y in range(size):
        for x in range(size):
            dx = x + 0.5 - center_local
            dy = y + 0.5 - center_local
            if dx * dx + dy * dy <= r2:
                mpx[x, y] = 255

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(canvas, (0, 0), mask)
    return out


def make_body_layer(image, rear_center, front_center, radius):
    """Копия изображения с прозрачными дырками (радиус radius - HOLE_SHRINK) на
    месте колёс, чтобы вращающиеся под телом колёса не просвечивали двойным
    контуром."""
    body = image.copy()
    px = body.load()
    w, h = body.size
    hole_r = radius - HOLE_SHRINK
    hole_r2 = hole_r * hole_r
    for cx, cy in (rear_center, front_center):
        left = max(0, int(cx - hole_r) - 1)
        right = min(w, int(cx + hole_r) + 2)
        top = max(0, int(cy - hole_r) - 1)
        bottom = min(h, int(cy + hole_r) + 2)
        for y in range(top, bottom):
            for x in range(left, right):
                dx = x + 0.5 - cx
                dy = y + 0.5 - cy
                if dx * dx + dy * dy <= hole_r2:
                    r_, g_, b_, _a = px[x, y]
                    px[x, y] = (r_, g_, b_, 0)
    return body


def main():
    if not SOURCE.exists():
        sys.exit(f"Не найден исходник: {SOURCE}")

    image = Image.open(SOURCE).convert("RGBA")

    detected = detect_wheels(image)
    if detected:
        rear_center, front_center, radius = detected
        print(
            f"Детекция: заднее колесо {rear_center}, переднее {front_center}, "
            f"r={radius:.1f}"
        )
    else:
        rear_center, front_center, radius = FALLBACK_REAR, FALLBACK_FRONT, FALLBACK_RADIUS
        print(
            "Детекция ненадёжна — использую запасные ориентиры: "
            f"заднее {rear_center}, переднее {front_center}, r={radius}"
        )

    wheel_rear = make_wheel_layer(image, rear_center, radius)
    wheel_front = make_wheel_layer(image, front_center, radius)
    body = make_body_layer(image, rear_center, front_center, radius)

    wheel_rear.save(OUT_DIR / "wheel_rear.png")
    wheel_front.save(OUT_DIR / "wheel_front.png")
    body.save(OUT_DIR / "body.png")
    print(
        "Сохранено: "
        f"{OUT_DIR / 'wheel_rear.png'}, {OUT_DIR / 'wheel_front.png'}, {OUT_DIR / 'body.png'}"
    )


if __name__ == "__main__":
    main()
