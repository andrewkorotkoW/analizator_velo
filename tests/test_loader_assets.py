"""Проверки слоёв иллюстрации велосипедиста для лоадера (app/static/img/loader/),
полученных из cyclist.png скриптом scripts/split_cyclist.py, и их геометрии,
пробрасываемой в CSS через loader_geometry.generated.css."""

import importlib.util
import json
import math
import re
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
LOADER_IMG_DIR = REPO_ROOT / "app" / "static" / "img" / "loader"
GEOMETRY_JSON = LOADER_IMG_DIR / "loader_geometry.json"
GEOMETRY_CSS = REPO_ROOT / "app" / "static" / "css" / "loader_geometry.generated.css"
LOADER_CSS = REPO_ROOT / "app" / "static" / "css" / "loader.css"


def _load_split_script():
    spec = importlib.util.spec_from_file_location(
        "split_cyclist", REPO_ROOT / "scripts" / "split_cyclist.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _geometry():
    return json.loads(GEOMETRY_JSON.read_text(encoding="utf-8"))


def test_three_layers_exist():
    assert (LOADER_IMG_DIR / "cyclist.png").is_file()
    assert (LOADER_IMG_DIR / "wheel_rear.png").is_file()
    assert (LOADER_IMG_DIR / "wheel_front.png").is_file()
    assert (LOADER_IMG_DIR / "body.png").is_file()


def test_geometry_json_exists_and_is_sane():
    geometry = _geometry()
    assert geometry["image_size"] == 360
    for side in ("rear", "front"):
        wheel = geometry["wheels"][side]
        # Радиус и центр должны попадать в разумный диапазон для колеса
        # велосипеда на иллюстрации 360x360 (не крошечный кружок, не половина
        # картинки, и не за её пределами).
        assert 30 <= wheel["r"] <= 120
        assert 0 <= wheel["cx"] <= geometry["image_size"]
        assert 0 <= wheel["cy"] <= geometry["image_size"]
    # Колёса не должны перекрываться центрами (заднее — слева от переднего).
    assert geometry["wheels"]["rear"]["cx"] < geometry["wheels"]["front"]["cx"]


def test_wheel_layers_are_square_rgba_with_opaque_pixels():
    for name in ("wheel_rear.png", "wheel_front.png"):
        with Image.open(LOADER_IMG_DIR / name) as img:
            assert img.mode == "RGBA"
            assert img.width == img.height
            alphas = img.getchannel("A").getdata()
            assert any(a > 0 for a in alphas), f"{name}: колесо не должно быть полностью прозрачным"


def test_wheel_layers_transparent_beyond_radius_plus_margin():
    """За пределами r + WHEEL_MARGIN в слое колеса не должно быть ни одного
    непрозрачного пикселя рамы — слой должен быть ТОЛЬКО колесом."""
    module = _load_split_script()
    geometry = _geometry()
    for side, name in (("rear", "wheel_rear.png"), ("front", "wheel_front.png")):
        wheel = geometry["wheels"][side]
        r_outer = wheel["r"] + module.WHEEL_MARGIN
        with Image.open(LOADER_IMG_DIR / name) as img:
            size = img.width
            center = size / 2.0
            px = img.load()
            bad = []
            for y in range(size):
                for x in range(size):
                    dx = x + 0.5 - center
                    dy = y + 0.5 - center
                    if math.hypot(dx, dy) > r_outer + 1.0:
                        if px[x, y][3] > 0:
                            bad.append((x, y))
            assert not bad, (
                f"{name}: найдены непрозрачные пиксели за пределами r+margin: {bad[:5]}"
            )


def test_body_layer_has_transparent_holes_at_wheel_centers():
    geometry = _geometry()
    with Image.open(LOADER_IMG_DIR / "body.png") as body:
        assert body.mode == "RGBA"
        assert body.size == (geometry["image_size"], geometry["image_size"])
        pixels = body.load()

        for side in ("rear", "front"):
            wheel = geometry["wheels"][side]
            cx, cy = round(wheel["cx"]), round(wheel["cy"])
            _, _, _, alpha = pixels[cx, cy]
            assert alpha == 0, (
                f"body.png должен быть прозрачным в центре колеса {side} ({cx}, {cy}), "
                f"чтобы вращающееся колесо снизу не давало двойного контура"
            )


def test_body_layer_keeps_corridor_pixels_opaque():
    """Точки на "коридорах" рамы, проходящих через дырку колеса (перья, вилка,
    переключатель), должны остаться непрозрачными — иначе рама обрывается на
    границе дырки."""
    module = _load_split_script()
    geometry = _geometry()
    rear = geometry["wheels"]["rear"]
    front = geometry["wheels"]["front"]

    checks = [
        # Середины коридоров от втулки к раме.
        (
            (rear["cx"] + module.REAR_SEAT_CLUSTER[0]) / 2,
            (rear["cy"] + module.REAR_SEAT_CLUSTER[1]) / 2,
        ),
        (
            (rear["cx"] + module.REAR_BOTTOM_BRACKET[0]) / 2,
            (rear["cy"] + module.REAR_BOTTOM_BRACKET[1]) / 2,
        ),
        (
            (front["cx"] + module.FRONT_FORK_CROWN[0]) / 2,
            (front["cy"] + module.FRONT_FORK_CROWN[1]) / 2,
        ),
    ]

    with Image.open(LOADER_IMG_DIR / "body.png") as body:
        pixels = body.load()
        for x, y in checks:
            _, _, _, alpha = pixels[round(x), round(y)]
            assert alpha > 0, f"коридор рамы прерван дыркой колеса в точке ({x}, {y})"


def test_body_layer_keeps_non_wheel_pixels_opaque():
    with Image.open(LOADER_IMG_DIR / "body.png") as body:
        pixels = body.load()
        # Точка на шлеме — заведомо не пересекается с дырками колёс.
        _, _, _, alpha = pixels[240, 40]
        assert alpha > 0, "непрозрачные части тела/шлема не должны быть вырезаны"


def _parse_generated_css_vars():
    text = GEOMETRY_CSS.read_text(encoding="utf-8")
    values = {}
    for match in re.finditer(r"--(velo-wheel-[a-z-]+):\s*([\d.]+)%;", text):
        values[match.group(1)] = float(match.group(2))
    return values


def test_generated_css_matches_geometry_json():
    """Проценты в loader_geometry.generated.css должны быть посчитаны из тех же
    (cx, cy, r), что лежат в loader_geometry.json — никаких ручных чисел."""
    geometry = _geometry()
    css_vars = _parse_generated_css_vars()

    for side in ("rear", "front"):
        expected = geometry["css_percent"][side]
        assert css_vars[f"velo-wheel-{side}-left"] == round(expected["left"], 3)
        assert css_vars[f"velo-wheel-{side}-top"] == round(expected["top"], 3)
        assert css_vars[f"velo-wheel-{side}-size"] == round(expected["size"], 3)


def test_loader_css_references_generated_variables():
    """loader.css не должен содержать вручную прописанную геометрию колёс —
    только ссылки на переменные из loader_geometry.generated.css."""
    text = LOADER_CSS.read_text(encoding="utf-8")
    assert "var(--velo-wheel-rear-left" in text
    assert "var(--velo-wheel-rear-top" in text
    assert "var(--velo-wheel-rear-size" in text
    assert "var(--velo-wheel-front-left" in text
    assert "var(--velo-wheel-front-top" in text
    assert "var(--velo-wheel-front-size" in text


def test_wheels_stack_below_body_via_z_index():
    text = LOADER_CSS.read_text(encoding="utf-8")
    wheel_block = re.search(r"\.velo-loader-wheel\s*\{[^}]*\}", text).group(0)
    body_block = re.search(r"\.velo-loader-body-img\s*\{[^}]*\}", text).group(0)
    wheel_z = int(re.search(r"z-index:\s*(\d+)", wheel_block).group(1))
    body_z = int(re.search(r"z-index:\s*(\d+)", body_block).group(1))
    assert body_z > wheel_z, "тело (рама) должно быть поверх колёс по z-index"
