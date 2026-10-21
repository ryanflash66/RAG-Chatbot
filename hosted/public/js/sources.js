// The right panel: the passages an answer cites (DAR-627). show() keeps each
// answer's sources under its id (the data-answer-id of its reply), so clicking an
// [n] citation in an older answer switches the panel back to that answer.
//   show(sources, answerId)  an answer is complete; its sources become the panel's
//   cite(answerId, n)        what clicking [n] in that answer does
//   clear()                  empty the panel; stored answers stay, so their citations still work
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  var EMPTY = '<p class="empty">The passages an answer uses appear here, with a link to each PDF page.</p>';
  // Excerpts run up to 700 characters (EXCERPT_CHARS in divrag/answer.py). Longer than this
  // they are clamped to five lines with a Show more toggle. 240 characters is about five lines
  // of the 300-360 px panel, so a shorter excerpt is never cut off without a toggle to open it.
  var CLAMP_CHARS = 240;
  var FLASH_MS = 1600;   // the length of .src.flash's animation in sources.css
  var byAnswer = Object.create(null);   // answerId -> {sources, question}
  var active = null, panel, box, flashed = null, flashTimer = 0;
  var returnTo = null;   // the citation that opened the drawer, focused again when it closes

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // Below 900 px the panel is a drawer; the Sources button in the top bar shows only then,
  // so its visibility says which layout is on without repeating base.css's breakpoint here.
  function isDrawer() {
    var toggle = document.getElementById("open-sources");
    return !!toggle && window.getComputedStyle(toggle).display !== "none";
  }

  function replyFor(answerId) {
    var replies = document.querySelectorAll("[data-answer-id]");
    for (var i = 0; i < replies.length; i++) {
      if (replies[i].getAttribute("data-answer-id") === answerId) return replies[i];
    }
    return null;
  }

  function questionFor(answerId) {
    var reply = replyFor(answerId);
    var exchange = reply && reply.closest(".exchange");
    var q = exchange && exchange.querySelector(".question");
    return q ? q.textContent.trim() : "";
  }

  // The answer whose sources the panel shows is marked in the thread, which matters
  // once DAR-619 keeps many answers there and a citation can switch between them.
  function markActive() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-answer-id]"), function (r) {
      r.classList.toggle("sources-shown", r.getAttribute("data-answer-id") === active);
    });
  }

  function itemHtml(s) {
    var n = Number(s.n), text = s.excerpt || "", long = text.length > CLAMP_CHARS;
    var textId = "src-" + n + "-text";
    var meta = [];
    if (s.page) {
      meta.push(s.page_end && s.page_end !== s.page
        ? "PDF pages " + R.escapeHtml(s.page) + "–" + R.escapeHtml(s.page_end)
        : "PDF page " + R.escapeHtml(s.page));
    }
    if (s.section) meta.push("Section " + R.escapeHtml(s.section));
    var actions = "";
    if (long) {
      actions += '<button type="button" class="src-more" aria-expanded="false" aria-controls="' + textId + '">Show more</button>';
    }
    if (s.url) {
      // url ends in #page=N when the page is known. Identical link texts get a hidden
      // source number so a screen reader's list of links tells them apart.
      actions += '<a class="src-link" href="' + R.escapeHtml(s.url) + '" target="_blank" rel="noopener">' +
        (s.page ? "Open the PDF at this page" : "Open the PDF") +
        '<span class="src-sr"> (source ' + n + ", opens in a new tab)</span></a>";
    }
    // tabindex=-1: a clicked citation moves focus here, so a screen reader reads the passage.
    // The clamp is on the inner <p>: on the padded box, the sixth line would show in the padding.
    return '<li class="src" id="src-' + n + '" data-n="' + n + '" tabindex="-1">' +
      '<div class="src-head"><span class="src-n"><span class="src-sr">Source </span>' + n + "</span>" +
      '<span class="src-title">' + R.escapeHtml(s.title) + "</span></div>" +
      (meta.length ? '<div class="src-meta">' + meta.join(" · ") + "</div>" : "") +
      (text ? '<div class="src-text"><p' + (long ? ' class="clamped"' : "") + ' id="' + textId + '">' + R.escapeHtml(text) + "</p></div>" : "") +
      (actions ? '<div class="src-actions">' + actions + "</div>" : "") +
      "</li>";
  }

  function render(answerId) {
    var entry = byAnswer[answerId];
    active = answerId;
    markActive();
    panel.scrollTop = 0;
    if (!entry) { box.innerHTML = EMPTY; return; }
    var sources = entry.sources, question = entry.question || questionFor(answerId);
    var label = !sources.length ? "No passages were used to answer"
      : sources.length === 1 ? "1 passage used to answer" : sources.length + " passages used to answer";
    var html = question
      ? '<p class="src-for">' + label + ' <span class="src-q">' + R.escapeHtml(question) + "</span></p>"
      : (sources.length ? "" : '<p class="empty">This answer has no sources.</p>');
    if (sources.length) {
      html += '<ol class="sources">' + sources.map(itemHtml).join("") + "</ol>";
      if (sources.some(function (s) { return /#page=\d+$/.test(s.url || ""); })) {
        html += '<p class="src-note">Safari may open the PDF at page 1. If it does, go to the page shown above.</p>';
      }
    }
    box.innerHTML = html;
  }

  // Scroll the panel itself, not the page: scrollIntoView would also move the window
  // and, on phones, the chat behind the drawer.
  function scrollToItem(item) {
    var top = panel.scrollTop + item.getBoundingClientRect().top - panel.getBoundingClientRect().top - 12;
    top = Math.max(0, top);
    if (panel.scrollTo) panel.scrollTo({ top: top, behavior: reducedMotion() ? "auto" : "smooth" });
    else panel.scrollTop = top;
  }

  function flash(item) {
    if (flashed) flashed.classList.remove("flash");
    clearTimeout(flashTimer);
    void item.offsetWidth;   // restarts the animation when the same passage is cited twice in a row
    item.classList.add("flash");
    flashed = item;
    // A timer rather than animationend, which never fires when reduced motion turns the animation off.
    flashTimer = setTimeout(function () { item.classList.remove("flash"); flashed = null; }, FLASH_MS);
  }

  // link: the clicked citation, if any, so focus can go back to it when the drawer closes.
  function cite(answerId, n, link) {
    if (!(answerId in byAnswer)) return;
    if (answerId !== active) render(answerId);
    var item = box.querySelector('.src[data-n="' + Number(n) + '"]');
    if (!item) return;
    // Open the drawer first: focus() skips an element whose drawer is still visibility: hidden.
    if (isDrawer()) {
      returnTo = link || null;
      App.drawers.open("sources-panel");
    }
    Array.prototype.forEach.call(box.querySelectorAll(".src.current"), function (li) { li.classList.remove("current"); });
    item.classList.add("current");
    item.focus({ preventScroll: true });
    scrollToItem(item);
    flash(item);
  }

  function onCitationClick(e) {
    var link = e.target.closest && e.target.closest("a.cite[data-cite]");
    if (!link) return;
    // The href (#src-n) is only a fallback; following it would jump the whole page.
    e.preventDefault();
    var reply = link.closest("[data-answer-id]");
    cite(reply ? reply.getAttribute("data-answer-id") : active, link.getAttribute("data-cite"), link);
  }

  // The chat replaces or removes exchanges (until DAR-619 a new question empties the
  // thread). An answer that has left the page drops its sources, and if the panel was
  // showing them it empties, so it never shows passages for an answer no longer there.
  function onThreadChange() {
    var present = Object.create(null);
    Array.prototype.forEach.call(document.querySelectorAll("[data-answer-id]"), function (r) {
      present[r.getAttribute("data-answer-id")] = true;
    });
    Object.keys(byAnswer).forEach(function (id) { if (!present[id]) delete byAnswer[id]; });
    if (active !== null && !present[active]) App.sources.clear();
  }

  // Closing the drawer (×, scrim or Escape, all in app.js) hides it with focus still
  // inside; send focus back to the citation that opened it so the reader keeps their place.
  function onPanelChange() {
    if (panel.classList.contains("open")) return;
    var link = returnTo;
    returnTo = null;
    if (link && document.contains(link) && panel.contains(document.activeElement)) link.focus();
  }

  function onToggleClick(e) {
    var button = e.target.closest && e.target.closest(".src-more");
    if (!button) return;
    var text = document.getElementById(button.getAttribute("aria-controls"));
    var open = button.getAttribute("aria-expanded") !== "true";
    if (text) text.classList.toggle("clamped", !open);
    button.setAttribute("aria-expanded", String(open));
    button.textContent = open ? "Show less" : "Show more";
  }

  App.sources = {
    init: function () {
      panel = document.getElementById("sources-panel");
      box = document.getElementById("sources");
      box.innerHTML = EMPTY;
      document.addEventListener("click", onCitationClick);
      box.addEventListener("click", onToggleClick);
      if (window.MutationObserver) {
        new MutationObserver(onThreadChange).observe(document.getElementById("thread") || document.body, { childList: true, subtree: true });
        new MutationObserver(onPanelChange).observe(panel, { attributes: true, attributeFilter: ["class"] });
      }
    },
    show: function (sources, answerId) {
      byAnswer[answerId] = { sources: sources || [], question: questionFor(answerId) };
      render(answerId);
    },
    cite: cite,
    clear: function () { active = null; markActive(); box.innerHTML = EMPTY; }
  };
})();
