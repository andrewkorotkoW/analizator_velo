#!/usr/bin/env python3
"""
Разрезает app/static/img/loader/cyclist.png на слои для анимации лоадера:
wheel_rear.png, wheel_front.png (колёса, вращаются) и body.png (рама/райдер,
неподвижная часть — колёса подложены под неё).

Геометрия (центр и радиус каждого колеса) определяется автоматически по самому
изображению, а не подбирается на глаз: для каждого колеса ищется крайняя точка
обода со стороны, свободной от рамы (левый край у заднего колеса, правый —
у переднего) и нижняя точка обода (рама всегда выше колеса, поэтому низ чист
у обоих). Из этих двух крайних точек однозначно считается (cx, cy, r).

Запуск:
    .venv/bin/python scripts/split_cyclist.py            # только слои + geometry.json
    .venv/bin/python scripts/split_cyclist.py --preview   # + preview-картинки для проверки глазами

Результаты:
    app/static/img/loader/wheel_rear.png
    app/static/img/loader/wheel_front.png
    app/static/img/loader/body.png
    app/static/img/loader/loader_geometry.json   — найденные (cx, cy, r) в px
    app/static/img/loader/preview_geometry.png   — исходник с нарисованными окружностями
    app/static/css/loader_geometry.generated.css — CSS-переменные, посчитанные из geometry.json

    --preview дополнительно:
    app/static/img/loader/preview_composite.png  — собранные слои (колёса + тело)
    app/static/img/loader/preview_frames.png     — кадры на 0/90/180/270°
"""
import json
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit(
        "Pillow не установлен. Установите его в окружение проекта:\n"
        "    .venv/bin/pip install Pillow\n"
        "и запустите скрипт снова: .venv/bin/python scripts/split_cyclist.py"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "app" / "static" / "img" / "loader" / "cyclist.png"
OUT_DIR = SOURCE.parent
CSS_OUT = REPO_ROOT / "app" / "static" / "css" / "loader_geometry.generated.css"
GEOMETRY_JSON = OUT_DIR / "loader_geometry.json"

ALPHA_OPAQUE_THRESHOLD = 128

# Запас по радиусу при вырезке колеса, чтобы не срезать антиалиасинг обода.
WHEEL_MARGIN = 2
# Ширина видимого в оригинале кольца покрышка+обод (от внешнего края внутрь).
TIRE_BAND_WIDTH = 18
# Радиус ступицы (синтетической).
HUB_RADIUS = 6
HUB_CAP_RADIUS = 3
# Вокруг втулки в body.png дырка всегда прозрачна (даже если попадает в
# "коридор" или прямоугольник переключателя) — синтетическую втулку рисует
# сам слой колеса, а не body.
HUB_HOLE_RADIUS = HUB_RADIUS + 3
SPOKE_COUNT = 16
SPOKE_WIDTH = 2  # px (~1.5px не отрисовать без сглаживания, берём ближайшее целое)
SPOKE_COLOR = (172, 172, 176, 235)
HUB_COLOR = (25, 25, 27, 255)
HUB_CAP_COLOR = (140, 140, 144, 255)

# Ширина "коридоров" рамы, проходящих через колесо в body.png.
CORRIDOR_WIDTH = 12

# Точки рамы (в координатах исходника 360x360), к которым идут коридоры от
# втулки каждого колеса. Подобраны по самой иллюстрации (см. preview_geometry.png
# и preview_composite.png для проверки) — это свойство конкретного рисунка,
# а не выводится из геометрии колеса.
REAR_SEAT_CLUSTER = (128, 200)
REAR_BOTTOM_BRACKET = (178, 258)
FRONT_FORK_CROWN = (243, 185)

# Прямоугольник кассеты/переключателя у заднего колеса (сохраняется в body.png
# целиком, не только коридором) — смещение от втулки заднего колеса.
REAR_DERAILLEUR_BOX_OFFSET = (-6, -10, 52, 32)  # (left, top, right, bottom) от hub


def _luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def _opaque(px, w, h, x, y):
    if x < 0 or y < 0 or x >= w or y >= h:
        return False
    return px[x, y][3] >= ALPHA_OPAQUE_THRESHOLD


def _dark(px, w, h, x, y, thresh=110):
    if x < 0 or y < 0 or x >= w or y >= h:
        return False
    r, g, b, a = px[x, y]
    return a >= ALPHA_OPAQUE_THRESHOLD and _luma(r, g, b) < thresh


def _ring_dark_fraction(px, w, h, cx, cy, r, n=180):
    """Доля точек на окружности радиуса r, которые тёмные и непрозрачные —
    мера того, что (cx, cy, r) действительно описывает сплошной тёмный обод."""
    hit = 0
    for i in range(n):
        ang = 2 * math.pi * i / n
        x = int(round(cx + r * math.cos(ang)))
        y = int(round(cy + r * math.sin(ang)))
        if _dark(px, w, h, x, y):
            hit += 1
    return hit / n


def _find_extreme_x(px, w, h, x_range, y_range, want_max):
    """Крайняя (левая/правая) непрозрачная точка в области + центр диапазона y,
    на котором эта крайняя x достигается (даёт оценку cy)."""
    best_x = None
    ys_at_best = []
    xs_iter = (
        range(x_range.stop - 1, x_range.start - 1, -1) if want_max else range(x_range.start, x_range.stop)
    )
    for y in y_range:
        found = None
        for x in xs_iter:
            if _opaque(px, w, h, x, y):
                found = x
                break
        if found is None:
            continue
        if best_x is None or (found > best_x if want_max else found < best_x):
            best_x = found
            ys_at_best = [y]
        elif found == best_x:
            ys_at_best.append(y)
    if best_x is None:
        return None
    return best_x, sum(ys_at_best) / len(ys_at_best)


def _find_bottom_y(px, w, h, x_range, y_range):
    """Нижняя непрозрачная точка в области + центр диапазона x, на котором она
    достигается (даёт оценку cx). Рама у обоих колёс всегда выше колеса, так
    что низ обода никогда ей не перекрыт."""
    best_y = None
    xs_at_best = []
    for x in x_range:
        found = None
        for y in range(y_range.stop - 1, y_range.start - 1, -1):
            if _opaque(px, w, h, x, y):
                found = y
                break
        if found is None:
            continue
        if best_y is None or found > best_y:
            best_y = found
            xs_at_best = [x]
        elif found == best_y:
            xs_at_best.append(x)
    if best_y is None:
        return None
    return best_y, sum(xs_at_best) / len(xs_at_best)


def detect_wheel(image, x_range, y_range, side):
    """side: 'rear' (свободный край слева, рама справа) или 'front' (свободный
    край справа, рама слева). Возвращает (cx, cy, r, ring_score) либо None."""
    w, h = image.size
    px = image.load()

    extreme = _find_extreme_x(px, w, h, x_range, y_range, want_max=(side == "front"))
    bottom = _find_bottom_y(px, w, h, x_range, y_range)
    if extreme is None or bottom is None:
        return None

    extreme_x, cy_est = extreme
    bottom_y, cx_est = bottom

    r = bottom_y - cy_est
    if r <= 0:
        return None
    cx = extreme_x - r if side == "front" else extreme_x + r
    cy = cy_est

    # Сверка: центр по низу и центр по крайней точке должны примерно совпасть.
    if abs(cx - cx_est) > 8:
        return None

    score = _ring_dark_fraction(px, w, h, cx, cy, r)
    return cx, cy, r, score


def detect_geometry(image):
    """Возвращает {'rear': (cx,cy,r), 'front': (cx,cy,r)} либо None, если
    детекция ненадёжна (низкий ring_score — окружность не легла на сплошной
    тёмный обод)."""
    w, h = image.size
    y_range = range(int(h * 0.4), h)

    rear = detect_wheel(image, range(0, w // 2), y_range, "rear")
    front = detect_wheel(image, range(w // 2, w), y_range, "front")
    if rear is None or front is None:
        return None
    if rear[3] < 0.8 or front[3] < 0.8:
        return None

    return {
        "rear": {"cx": rear[0], "cy": rear[1], "r": rear[2]},
        "front": {"cx": front[0], "cy": front[1], "r": front[2]},
    }


# Запасная геометрия (если автодетекция когда-нибудь не сработает на новой
# иллюстрации — например, обод не сплошной тёмный). Подобрана под текущую
# cyclist.png теми же измерениями, что делает detect_geometry().
FALLBACK_GEOMETRY = {
    "rear": {"cx": 90.0, "cy": 259.5, "r": 61.5},
    "front": {"cx": 269.0, "cy": 260.0, "r": 61.0},
}


def _dist_point_to_segment(px_, py_, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(px_ - ax, py_ - ay)
    t = ((px_ - ax) * dx + (py_ - ay) * dy) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(px_ - (ax + t * dx), py_ - (ay + t * dy))


def make_wheel_layer(image, cx, cy, r):
    """Слой колеса: кольцо покрышка+обод — РЕАЛЬНЫЕ пиксели исходника
    (annulus [r-TIRE_BAND_WIDTH, r+WHEEL_MARGIN]), внутри — синтетические спицы
    и втулка. Всё за пределами r+WHEEL_MARGIN прозрачно. Пикселей рамы в слое
    быть не должно, т.к. они лежат вне этого кольца (рама вплотную к втулке
    может частично попасть в кольцо только у самой ступицы — этого не бывает,
    т.к. внутренний радиус кольца заведомо больше ступицы)."""
    r_outer = r + WHEEL_MARGIN
    r_inner = r - TIRE_BAND_WIDTH
    size = int(math.ceil(2 * r_outer))
    center_local = size / 2.0

    src_w, src_h = image.size
    src_px = image.load()

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cpx = canvas.load()

    r_outer2 = r_outer * r_outer
    r_inner2 = r_inner * r_inner
    for ly in range(size):
        for lx in range(size):
            dx = lx + 0.5 - center_local
            dy = ly + 0.5 - center_local
            d2 = dx * dx + dy * dy
            if d2 > r_outer2 or d2 < r_inner2:
                continue
            sx = int(round(cx - r_outer + lx))
            sy = int(round(cy - r_outer + ly))
            if 0 <= sx < src_w and 0 <= sy < src_h:
                cpx[lx, ly] = src_px[sx, sy]

    draw = ImageDraw.Draw(canvas)

    # Спицы: тонкие линии от ступицы до внутреннего края кольца покрышки.
    for i in range(SPOKE_COUNT):
        ang = 2 * math.pi * i / SPOKE_COUNT
        x0 = center_local + HUB_RADIUS * math.cos(ang)
        y0 = center_local + HUB_RADIUS * math.sin(ang)
        x1 = center_local + r_inner * math.cos(ang)
        y1 = center_local + r_inner * math.sin(ang)
        draw.line([(x0, y0), (x1, y1)], fill=SPOKE_COLOR, width=SPOKE_WIDTH)

    # Лёгкий прозрачный сектор-тень для объёма (как блик/тень в иллюстрации).
    shade_box = [
        center_local - r_inner,
        center_local - r_inner,
        center_local + r_inner,
        center_local + r_inner,
    ]
    draw.pieslice(shade_box, start=200, end=235, fill=(0, 0, 0, 40))

    # Втулка.
    draw.ellipse(
        [center_local - HUB_RADIUS, center_local - HUB_RADIUS, center_local + HUB_RADIUS, center_local + HUB_RADIUS],
        fill=HUB_COLOR,
    )
    draw.ellipse(
        [
            center_local - HUB_CAP_RADIUS,
            center_local - HUB_CAP_RADIUS,
            center_local + HUB_CAP_RADIUS,
            center_local + HUB_CAP_RADIUS,
        ],
        fill=HUB_CAP_COLOR,
    )

    # Финальная маска — гарантирует прозрачность строго за r_outer, даже если
    # штриховка/AA спиц случайно вышла за расчётный внутренний радиус.
    mask = Image.new("L", (size, size), 0)
    mpx = mask.load()
    for ly in range(size):
        for lx in range(size):
            dx = lx + 0.5 - center_local
            dy = ly + 0.5 - center_local
            if dx * dx + dy * dy <= r_outer2:
                mpx[lx, ly] = 255
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(canvas, (0, 0), mask)
    return out


def _corridor_segments(side, cx, cy):
    if side == "rear":
        return [((cx, cy), REAR_SEAT_CLUSTER), ((cx, cy), REAR_BOTTOM_BRACKET)]
    return [((cx, cy), FRONT_FORK_CROWN)]


def _derailleur_box(side, cx, cy):
    if side != "rear":
        return None
    left, top, right, bottom = REAR_DERAILLEUR_BOX_OFFSET
    return (cx + left, cy + top, cx + right, cy + bottom)


def make_body_layer(image, geometry):
    """Копия исходника с прозрачной дыркой на месте каждого колеса (диск
    r+WHEEL_MARGIN), но с сохранёнными "коридорами" рамы, проходящими через
    колесо от втулки к раме (иначе перья/вилка/переключатель обрываются на
    границе дырки)."""
    body = image.copy()
    px = body.load()
    w, h = body.size

    for side, geom in geometry.items():
        cx, cy, r = geom["cx"], geom["cy"], geom["r"]
        r_outer = r + WHEEL_MARGIN
        r_outer2 = r_outer * r_outer
        segments = _corridor_segments(side, cx, cy)
        box = _derailleur_box(side, cx, cy)
        half_w = CORRIDOR_WIDTH / 2.0

        left = max(0, int(cx - r_outer) - 1)
        right = min(w, int(cx + r_outer) + 2)
        top = max(0, int(cy - r_outer) - 1)
        bottom = min(h, int(cy + r_outer) + 2)

        hub_hole_r2 = HUB_HOLE_RADIUS * HUB_HOLE_RADIUS
        for y in range(top, bottom):
            for x in range(left, right):
                dx = x + 0.5 - cx
                dy = y + 0.5 - cy
                dist2_center = dx * dx + dy * dy
                if dist2_center > r_outer2:
                    continue
                if dist2_center > hub_hole_r2:
                    if box and box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                        continue
                    in_corridor = any(
                        _dist_point_to_segment(x + 0.5, y + 0.5, ax, ay, bx, by) <= half_w
                        for (ax, ay), (bx, by) in segments
                    )
                    if in_corridor:
                        continue
                r_, g_, b_, _a = px[x, y]
                px[x, y] = (r_, g_, b_, 0)

    return body


def save_preview_geometry(image, geometry):
    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    colors = {"rear": (255, 0, 0, 255), "front": (0, 140, 255, 255)}
    for side, geom in geometry.items():
        cx, cy, r = geom["cx"], geom["cy"], geom["r"]
        color = colors.get(side, (0, 255, 0, 255))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
        draw.ellipse(
            [cx - r - WHEEL_MARGIN, cy - r - WHEEL_MARGIN, cx + r + WHEEL_MARGIN, cy + r + WHEEL_MARGIN],
            outline=(0, 200, 0, 255),
            width=1,
        )
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=color)
    preview.save(OUT_DIR / "preview_geometry.png")


def save_preview_composite(wheel_rear, wheel_front, body, geometry):
    canvas = Image.new("RGBA", body.size, (255, 255, 255, 255))
    for side, layer in (("rear", wheel_rear), ("front", wheel_front)):
        geom = geometry[side]
        r_outer = geom["r"] + WHEEL_MARGIN
        left = int(round(geom["cx"] - r_outer))
        top = int(round(geom["cy"] - r_outer))
        canvas.paste(layer, (left, top), layer)
    canvas.paste(body, (0, 0), body)
    canvas.save(OUT_DIR / "preview_composite.png")


def save_preview_frames(wheel_rear, wheel_front, body, geometry):
    frame_w, frame_h = body.size
    sheet = Image.new("RGBA", (frame_w * 4, frame_h), (255, 255, 255, 255))
    for i, angle in enumerate((0, 90, 180, 270)):
        canvas = Image.new("RGBA", body.size, (255, 255, 255, 255))
        for side, layer in (("rear", wheel_rear), ("front", wheel_front)):
            geom = geometry[side]
            r_outer = geom["r"] + WHEEL_MARGIN
            rotated = layer.rotate(-angle, resample=Image.BICUBIC, center=(layer.width / 2, layer.height / 2))
            left = int(round(geom["cx"] - r_outer))
            top = int(round(geom["cy"] - r_outer))
            canvas.paste(rotated, (left, top), rotated)
        canvas.paste(body, (0, 0), body)
        sheet.paste(canvas, (i * frame_w, 0))
    sheet.save(OUT_DIR / "preview_frames.png")


def wheel_css_vars(geometry, image_size):
    """Проценты от квадратной сцены (относительно image_size=360) для каждого
    колеса: left/top — угол слоя (cx/cy - r_outer), size — сторона слоя
    (2 * r_outer). Единственное место, где геометрия колеса превращается в
    CSS-проценты — дальше эти числа не перебиваются руками нигде."""
    out = {}
    for side, geom in geometry.items():
        r_outer = geom["r"] + WHEEL_MARGIN
        left = (geom["cx"] - r_outer) / image_size * 100
        top = (geom["cy"] - r_outer) / image_size * 100
        size = (2 * r_outer) / image_size * 100
        out[side] = {"left": left, "top": top, "size": size}
    return out


def save_geometry_json(geometry, image_size):
    payload = {
        "image_size": image_size,
        "wheel_margin": WHEEL_MARGIN,
        "wheels": geometry,
        "css_percent": wheel_css_vars(geometry, image_size),
    }
    GEOMETRY_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_geometry_css(geometry, image_size):
    css_vars = wheel_css_vars(geometry, image_size)
    lines = [
        "/* Автосгенерировано scripts/split_cyclist.py из loader_geometry.json.",
        "   Не редактировать руками — пересчитывается вместе со слоями колёс. */",
        ":root {",
    ]
    for side in ("rear", "front"):
        v = css_vars[side]
        lines.append(f"  --velo-wheel-{side}-left: {v['left']:.3f}%;")
        lines.append(f"  --velo-wheel-{side}-top: {v['top']:.3f}%;")
        lines.append(f"  --velo-wheel-{side}-size: {v['size']:.3f}%;")
    lines.append("}")
    CSS_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if not SOURCE.exists():
        sys.exit(f"Не найден исходник: {SOURCE}")

    image = Image.open(SOURCE).convert("RGBA")
    image_size = image.size[0]

    geometry = detect_geometry(image)
    if geometry:
        print(
            "Детекция: "
            f"заднее cx={geometry['rear']['cx']:.1f} cy={geometry['rear']['cy']:.1f} r={geometry['rear']['r']:.1f}; "
            f"переднее cx={geometry['front']['cx']:.1f} cy={geometry['front']['cy']:.1f} r={geometry['front']['r']:.1f}"
        )
    else:
        geometry = FALLBACK_GEOMETRY
        print("Детекция ненадёжна — использую запасную геометрию:", geometry)

    wheel_rear = make_wheel_layer(image, geometry["rear"]["cx"], geometry["rear"]["cy"], geometry["rear"]["r"])
    wheel_front = make_wheel_layer(image, geometry["front"]["cx"], geometry["front"]["cy"], geometry["front"]["r"])
    body = make_body_layer(image, geometry)

    wheel_rear.save(OUT_DIR / "wheel_rear.png")
    wheel_front.save(OUT_DIR / "wheel_front.png")
    body.save(OUT_DIR / "body.png")
    save_preview_geometry(image, geometry)
    save_geometry_json(geometry, image_size)
    save_geometry_css(geometry, image_size)

    print(
        "Сохранено: "
        f"{OUT_DIR / 'wheel_rear.png'}, {OUT_DIR / 'wheel_front.png'}, {OUT_DIR / 'body.png'}, "
        f"{GEOMETRY_JSON}, {OUT_DIR / 'preview_geometry.png'}, {CSS_OUT}"
    )

    if "--preview" in sys.argv:
        save_preview_composite(wheel_rear, wheel_front, body, geometry)
        save_preview_frames(wheel_rear, wheel_front, body, geometry)
        print(f"Preview: {OUT_DIR / 'preview_composite.png'}, {OUT_DIR / 'preview_frames.png'}")


if __name__ == "__main__":
    main()
