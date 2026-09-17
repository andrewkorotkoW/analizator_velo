/**
 * VeloLoader — единый компонент оверлея-загрузчика (шоссейный велосипед на дороге)
 * для anal_velo. Используется при загрузке файлов/фото (upload), распознавании
 * фото (ocr) и сборке экспорта (export).
 *
 * Чистые функции (formatProgressLabel, getOverlayConfig, computeProgressPercent)
 * не трогают DOM и могут быть прогнаны напрямую через node — см. module.exports внизу.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory();
  } else {
    root.VeloLoader = factory();
  }
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";

  var MIN_VISIBLE_MS = 400;

  var OVERLAY_TEXT = {
    upload: "Загружаем…",
    ocr: "Распознаём фото…",
    export: "Собираем файл…",
  };

  /** Подпись прогресса вида "Загружаем… N из M". Если total неизвестен — просто "Загружаем…". */
  function formatProgressLabel(current, total) {
    if (!total || total <= 0) {
      return OVERLAY_TEXT.upload;
    }
    var n = Math.max(1, Math.min(Number(current) || 1, total));
    return OVERLAY_TEXT.upload + " " + n + " из " + total;
  }

  /** Текст/поведение оверлея для типа операции: 'upload' | 'ocr' | 'export'. */
  function getOverlayConfig(kind) {
    var title = OVERLAY_TEXT[kind] || OVERLAY_TEXT.upload;
    return {
      kind: kind,
      title: title,
      showProgress: kind === "upload",
    };
  }

  /** Процент прогресса (0..100) по байтам, переданным XHR upload.onprogress. */
  function computeProgressPercent(loaded, total) {
    if (!total || total <= 0) {
      return 0;
    }
    var pct = (Number(loaded) || 0) / total * 100;
    if (pct < 0) return 0;
    if (pct > 100) return 100;
    return pct;
  }

  var DEFAULT_IMG_BASE = "/static/img/loader/";

  /**
   * Базовый путь до app/static/img/loader/ для картинок велосипедиста, выведенный
   * из URL самого loader.js (чтобы работать независимо от префикса, под которым
   * Flask монтирует /static). scriptSrc — значение document.currentScript.src.
   * Если распознать не удалось (script загружен не как файл js/loader.js,
   * например инлайново в тестах) — используется DEFAULT_IMG_BASE.
   */
  function computeImageBase(scriptSrc) {
    if (typeof scriptSrc === "string" && scriptSrc.length) {
      var match = scriptSrc.match(/^(.*\/)js\/loader\.js(?:[?#].*)?$/);
      if (match) {
        return match[1] + "img/loader/";
      }
    }
    return DEFAULT_IMG_BASE;
  }

  var api = {
    MIN_VISIBLE_MS: MIN_VISIBLE_MS,
    formatProgressLabel: formatProgressLabel,
    getOverlayConfig: getOverlayConfig,
    computeProgressPercent: computeProgressPercent,
    computeImageBase: computeImageBase,
  };

  // ---- DOM-зависимая часть: не выполняется при прогоне чистых функций через node ----
  if (typeof document !== "undefined") {
    var IMG_BASE = computeImageBase(
      document.currentScript && document.currentScript.src
    );

    var state = {
      overlayEl: null,
      titleEl: null,
      progressWrapEl: null,
      progressBarEl: null,
      progressLabelEl: null,
      visible: false,
      shownAt: 0,
      hideTimer: null,
    };

    var el = function (tag, className) {
      var node = document.createElement(tag);
      if (className) {
        node.className = className;
      }
      return node;
    };

    var buildScene = function () {
      var scene = el("div", "velo-loader-scene");
      scene.setAttribute("aria-hidden", "true");

      var road = el("div", "velo-loader-road");
      road.appendChild(el("div", "velo-loader-road-dashes"));
      scene.appendChild(road);

      scene.appendChild(el("div", "velo-loader-shadow"));

      var speedlines = el("div", "velo-loader-speedlines");
      speedlines.appendChild(el("div", "velo-loader-speedline"));
      speedlines.appendChild(el("div", "velo-loader-speedline"));
      speedlines.appendChild(el("div", "velo-loader-speedline"));
      scene.appendChild(speedlines);

      var bike = el("div", "velo-loader-bike");

      var wheelRear = el("img", "velo-loader-wheel velo-loader-wheel-rear");
      wheelRear.src = IMG_BASE + "wheel_rear.png";
      wheelRear.alt = "";
      bike.appendChild(wheelRear);

      var wheelFront = el("img", "velo-loader-wheel velo-loader-wheel-front");
      wheelFront.src = IMG_BASE + "wheel_front.png";
      wheelFront.alt = "";
      bike.appendChild(wheelFront);

      var body = el("img", "velo-loader-body-img");
      body.src = IMG_BASE + "body.png";
      body.alt = "";
      bike.appendChild(body);

      scene.appendChild(bike);
      return scene;
    };

    var ensureMounted = function () {
      if (state.overlayEl) {
        return;
      }
      var overlay = el("div", "velo-loader-overlay");
      overlay.id = "veloLoaderOverlay";
      overlay.setAttribute("role", "status");
      overlay.setAttribute("aria-live", "polite");
      overlay.hidden = true;

      var panel = el("div", "velo-loader-panel");
      panel.appendChild(buildScene());

      var text = el("div", "velo-loader-text");
      var title = el("div", "velo-loader-title");
      text.appendChild(title);

      var progressWrap = el("div", "velo-loader-progress");
      progressWrap.hidden = true;
      var progressTrack = el("div", "velo-loader-progress-track");
      var progressBar = el("div", "velo-loader-progress-bar");
      progressTrack.appendChild(progressBar);
      progressWrap.appendChild(progressTrack);
      var progressLabel = el("div", "velo-loader-progress-label");
      progressWrap.appendChild(progressLabel);
      text.appendChild(progressWrap);

      panel.appendChild(text);
      overlay.appendChild(panel);
      document.body.appendChild(overlay);

      state.overlayEl = overlay;
      state.titleEl = title;
      state.progressWrapEl = progressWrap;
      state.progressBarEl = progressBar;
      state.progressLabelEl = progressLabel;
    };

    var render = function (kind, progress) {
      var config = getOverlayConfig(kind);
      if (config.showProgress && progress && progress.fileCount) {
        state.titleEl.textContent = formatProgressLabel(progress.fileIndex || 1, progress.fileCount);
      } else {
        state.titleEl.textContent = config.title;
      }

      if (config.showProgress && progress && progress.total) {
        var pct = computeProgressPercent(progress.loaded, progress.total);
        state.progressWrapEl.hidden = false;
        state.progressBarEl.style.width = pct + "%";
        state.progressLabelEl.textContent = Math.round(pct) + "%";
      } else {
        state.progressWrapEl.hidden = true;
      }
    };

    /** Показать оверлей. kind: 'upload' | 'ocr' | 'export'. progress: {loaded,total,fileIndex,fileCount} (опционально). */
    api.show = function (kind, progress) {
      ensureMounted();
      if (state.hideTimer) {
        clearTimeout(state.hideTimer);
        state.hideTimer = null;
      }
      if (!state.visible) {
        state.shownAt = Date.now();
      }
      state.visible = true;
      state.overlayEl.hidden = false;
      render(kind, progress);
    };

    /** Обновить текст/прогресс уже показанного оверлея (например, при переходе upload -> ocr). */
    api.update = function (kind, progress) {
      if (!state.visible) {
        return;
      }
      render(kind, progress);
    };

    /** Скрыть оверлей, гарантируя минимум MIN_VISIBLE_MS показа, чтобы не мигать на быстрых ответах. */
    api.hide = function () {
      if (!state.overlayEl || !state.visible) {
        return;
      }
      var elapsed = Date.now() - state.shownAt;
      var remaining = MIN_VISIBLE_MS - elapsed;
      if (remaining > 0) {
        state.hideTimer = setTimeout(function () {
          state.hideTimer = null;
          state.visible = false;
          state.overlayEl.hidden = true;
        }, remaining);
      } else {
        state.visible = false;
        state.overlayEl.hidden = true;
      }
    };
  }

  return api;
});
