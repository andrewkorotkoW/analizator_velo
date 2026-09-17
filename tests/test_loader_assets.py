"""Проверки слоёв иллюстрации велосипедиста для лоадера (app/static/img/loader/),
полученных из cyclist.png скриптом scripts/split_cyclist.py."""

import importlib.util
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
LOADER_IMG_DIR = REPO_ROOT / "app" / "static" / "img" / "loader"


def _load_split_script():
    spec = importlib.util.spec_from_file_location(
        "split_cyclist", REPO_ROOT / "scripts" / "split_cyclist.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_three_layers_exist():
    assert (LOADER_IMG_DIR / "cyclist.png").is_file()
    assert (LOADER_IMG_DIR / "wheel_rear.png").is_file()
    assert (LOADER_IMG_DIR / "wheel_front.png").is_file()
    assert (LOADER_IMG_DIR / "body.png").is_file()


def test_wheel_layers_are_square_rgba_with_opaque_pixels():
    for name in ("wheel_rear.png", "wheel_front.png"):
        with Image.open(LOADER_IMG_DIR / name) as img:
            assert img.mode == "RGBA"
            assert img.width == img.height
            alphas = img.getchannel("A").getdata()
            assert any(a > 0 for a in alphas), f"{name}: колесо не должно быть полностью прозрачным"


def test_body_layer_has_transparent_holes_at_wheel_centers():
    script = _load_split_script()

    with Image.open(LOADER_IMG_DIR / "body.png") as body:
        assert body.mode == "RGBA"
        assert body.size == (360, 360)
        pixels = body.load()

        for cx, cy in (script.FALLBACK_REAR, script.FALLBACK_FRONT):
            _, _, _, alpha = pixels[cx, cy]
            assert alpha == 0, (
                f"body.png должен быть прозрачным в центре колеса ({cx}, {cy}), "
                f"чтобы вращающееся колесо снизу не давало двойного контура"
            )


def test_body_layer_keeps_non_wheel_pixels_opaque():
    with Image.open(LOADER_IMG_DIR / "body.png") as body:
        pixels = body.load()
        # Точка на шлеме — заведомо не пересекается с дырками колёс.
        _, _, _, alpha = pixels[240, 40]
        assert alpha > 0, "непрозрачные части тела/шлема не должны быть вырезаны"
