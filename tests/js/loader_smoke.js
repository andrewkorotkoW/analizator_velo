// Node smoke-тест чистых функций app/static/js/loader.js (без DOM/браузера).
// Запуск: node tests/js/loader_smoke.js
//
// CommonJS (а не .mjs/ESM): loader.js — UMD-модуль, объявленный через
// module.exports, и в этом окружении установлен Node v12.13.0, где запуск
// .mjs как точки входа падает с ERR_REQUIRE_ESM без флага --experimental-modules.
// Обычный require() работает без флагов на любой версии Node.

var assert = require("assert");
var loaderModule = require("../../app/static/js/loader.js");

var formatProgressLabel = loaderModule.formatProgressLabel;
var getOverlayConfig = loaderModule.getOverlayConfig;

// ---- formatProgressLabel: "Загружаем… N из M" ----

assert.strictEqual(formatProgressLabel(1, 5), "Загружаем… 1 из 5", "базовый случай 1 из 5");
assert.strictEqual(formatProgressLabel(3, 5), "Загружаем… 3 из 5", "базовый случай 3 из 5");
assert.strictEqual(formatProgressLabel(5, 5), "Загружаем… 5 из 5", "последний файл в пачке");

// total не задан или <= 0 — просто "Загружаем…" без счётчика.
assert.strictEqual(formatProgressLabel(1, 0), "Загружаем…", "total=0 без счётчика");
assert.strictEqual(formatProgressLabel(1, -1), "Загружаем…", "отрицательный total без счётчика");
assert.strictEqual(
  formatProgressLabel(1, undefined),
  "Загружаем…",
  "total не задан — без счётчика"
);
assert.strictEqual(formatProgressLabel(1, null), "Загружаем…", "total=null без счётчика");

// current выходит за границы [1, total] — должен быть прижат к границе.
assert.strictEqual(formatProgressLabel(0, 5), "Загружаем… 1 из 5", "current=0 прижимается к 1");
assert.strictEqual(
  formatProgressLabel(-3, 5),
  "Загружаем… 1 из 5",
  "отрицательный current прижимается к 1"
);
assert.strictEqual(
  formatProgressLabel(10, 5),
  "Загружаем… 5 из 5",
  "current больше total прижимается к total"
);
assert.strictEqual(
  formatProgressLabel(undefined, 5),
  "Загружаем… 1 из 5",
  "current не задан — трактуется как 1"
);

// ---- getOverlayConfig: выбор текста/поведения по типу операции ----

var uploadConfig = getOverlayConfig("upload");
assert.strictEqual(uploadConfig.title, "Загружаем…", "заголовок для upload");
assert.strictEqual(uploadConfig.showProgress, true, "upload показывает прогресс");

var ocrConfig = getOverlayConfig("ocr");
assert.strictEqual(ocrConfig.title, "Распознаём фото…", "заголовок для ocr");
assert.strictEqual(ocrConfig.showProgress, false, "ocr не показывает прогресс");

var exportConfig = getOverlayConfig("export");
assert.strictEqual(exportConfig.title, "Собираем файл…", "заголовок для export");
assert.strictEqual(exportConfig.showProgress, false, "export не показывает прогресс");

// Неизвестный тип операции не должен падать — используется текст upload по умолчанию.
var unknownConfig = getOverlayConfig("something-else");
assert.strictEqual(
  unknownConfig.title,
  "Загружаем…",
  "неизвестный kind — заголовок по умолчанию (upload)"
);
assert.strictEqual(
  unknownConfig.showProgress,
  false,
  "неизвестный kind — прогресс не показывается (строгое сравнение с 'upload')"
);

console.log("loader_smoke: все проверки пройдены");
