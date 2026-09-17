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
var computeImageBase = loaderModule.computeImageBase;

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

// ---- computeImageBase: путь до app/static/img/loader/ по URL самого loader.js ----

assert.strictEqual(
  computeImageBase("https://example.com/static/js/loader.js"),
  "https://example.com/static/img/loader/",
  "базовый путь выводится из URL loader.js"
);
assert.strictEqual(
  computeImageBase("/static/js/loader.js?v=3"),
  "/static/img/loader/",
  "query-строка после имени файла не мешает"
);
assert.strictEqual(
  computeImageBase(undefined),
  "/static/img/loader/",
  "без currentScript — путь по умолчанию"
);
assert.strictEqual(
  computeImageBase(""),
  "/static/img/loader/",
  "пустая строка — путь по умолчанию"
);
assert.strictEqual(
  computeImageBase("/static/js/other.js"),
  "/static/img/loader/",
  "неожиданное имя файла скрипта — путь по умолчанию"
);

// ---- DOM: show() строит оверлей с телом и двумя колёсами (три <img>) ----
// Node здесь без jsdom/браузера, поэтому DOM подменяется минимальной заглушкой,
// которой хватает для того, что делает ensureMounted() в loader.js.

function makeFakeElement(tag) {
  return {
    tagName: String(tag).toUpperCase(),
    className: "",
    style: {},
    children: [],
    hidden: false,
    setAttribute: function (name, value) {
      this[name] = value;
    },
    appendChild: function (child) {
      this.children.push(child);
      return child;
    },
  };
}

function collectImgSrcs(node, out) {
  out = out || [];
  if (node.tagName === "IMG") {
    out.push(node.src);
  }
  node.children.forEach(function (child) {
    collectImgSrcs(child, out);
  });
  return out;
}

global.document = {
  currentScript: null,
  body: makeFakeElement("body"),
  createElement: makeFakeElement,
};

var loaderPath = require.resolve("../../app/static/js/loader.js");
delete require.cache[loaderPath];
var domLoaderModule = require("../../app/static/js/loader.js");

domLoaderModule.show("upload", { fileIndex: 1, fileCount: 3 });

var imgSrcs = collectImgSrcs(global.document.body);
assert.strictEqual(
  imgSrcs.length,
  3,
  "show() строит оверлей ровно с тремя <img>: тело + переднее и заднее колёса"
);

var imgBasenames = imgSrcs
  .map(function (src) {
    return String(src).split("/").pop();
  })
  .sort();
assert.deepStrictEqual(
  imgBasenames,
  ["body.png", "wheel_front.png", "wheel_rear.png"],
  "img ссылаются на body.png, wheel_front.png и wheel_rear.png"
);

delete global.document;

console.log("loader_smoke: все проверки пройдены");
