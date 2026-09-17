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

  var api = {
    MIN_VISIBLE_MS: MIN_VISIBLE_MS,
    formatProgressLabel: formatProgressLabel,
    getOverlayConfig: getOverlayConfig,
    computeProgressPercent: computeProgressPercent,
  };

  // ---- DOM-зависимая часть: не выполняется при прогоне чистых функций через node ----
  if (typeof document !== "undefined") {
    var BIKE_SVG =
      '<svg class="velo-loader-svg" viewBox="0 0 200 110" xmlns="http://www.w3.org/2000/svg" focusable="false">' +
        '<line class="velo-loader-road" x1="0" y1="90" x2="200" y2="90" />' +
        '<g class="velo-loader-dashes">' +
          '<g class="velo-loader-dashes-track">' +
            '<rect x="-30" y="88" width="14" height="4" rx="2" />' +
            '<rect x="0" y="88" width="14" height="4" rx="2" />' +
            '<rect x="30" y="88" width="14" height="4" rx="2" />' +
            '<rect x="60" y="88" width="14" height="4" rx="2" />' +
            '<rect x="90" y="88" width="14" height="4" rx="2" />' +
            '<rect x="120" y="88" width="14" height="4" rx="2" />' +
            '<rect x="150" y="88" width="14" height="4" rx="2" />' +
            '<rect x="180" y="88" width="14" height="4" rx="2" />' +
            '<rect x="210" y="88" width="14" height="4" rx="2" />' +
          "</g>" +
        "</g>" +
        '<g class="velo-loader-body">' +
          '<path class="velo-loader-frame-line" d="M55,72 L90,38 L125,38 L140,72 M90,38 L90,72 L125,38" />' +
          '<path class="velo-loader-frame-line" d="M125,38 L129,29" />' +
          '<path class="velo-loader-handlebar" d="M121,28 C127,25 133,26 135,31 C137,36 133,39 128,38" />' +
          '<path class="velo-loader-frame-line" d="M90,38 L94,32" />' +
          '<circle class="velo-loader-crank" cx="90" cy="72" r="4" />' +
          '<path class="velo-loader-frame-line" d="M90,72 L98,78 M90,72 L82,66" />' +
          '<g transform="translate(55,72)">' +
            '<g class="velo-loader-wheel-spin">' +
              '<circle class="velo-loader-tire" r="14" />' +
              '<circle class="velo-loader-hub" r="2.4" />' +
              '<path class="velo-loader-spokes" d="M0,-11 L0,11 M-9.5,-5.5 L9.5,5.5 M-9.5,5.5 L9.5,-5.5" />' +
            "</g>" +
          "</g>" +
          '<g transform="translate(140,72)">' +
            '<g class="velo-loader-wheel-spin">' +
              '<circle class="velo-loader-tire" r="14" />' +
              '<circle class="velo-loader-hub" r="2.4" />' +
              '<path class="velo-loader-spokes" d="M0,-11 L0,11 M-9.5,-5.5 L9.5,5.5 M-9.5,5.5 L9.5,-5.5" />' +
            "</g>" +
          "</g>" +
        "</g>" +
      "</svg>";

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

    var ensureMounted = function () {
      if (state.overlayEl) {
        return;
      }
      var overlay = document.createElement("div");
      overlay.className = "velo-loader-overlay";
      overlay.id = "veloLoaderOverlay";
      overlay.setAttribute("role", "status");
      overlay.setAttribute("aria-live", "polite");
      overlay.hidden = true;
      overlay.innerHTML =
        '<div class="velo-loader-panel">' +
          '<div class="velo-loader-scene" aria-hidden="true">' + BIKE_SVG + "</div>" +
          '<div class="velo-loader-text">' +
            '<div class="velo-loader-title" data-role="title"></div>' +
            '<div class="velo-loader-progress" data-role="progress-wrap" hidden>' +
              '<div class="velo-loader-progress-track"><div class="velo-loader-progress-bar" data-role="progress-bar"></div></div>' +
              '<div class="velo-loader-progress-label" data-role="progress-label"></div>' +
            "</div>" +
          "</div>" +
        "</div>";
      document.body.appendChild(overlay);

      state.overlayEl = overlay;
      state.titleEl = overlay.querySelector('[data-role="title"]');
      state.progressWrapEl = overlay.querySelector('[data-role="progress-wrap"]');
      state.progressBarEl = overlay.querySelector('[data-role="progress-bar"]');
      state.progressLabelEl = overlay.querySelector('[data-role="progress-label"]');
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
