// Shared helpers: escaping, the answer's safe Markdown and time formatting.
(function () {
  "use strict";
  var App = window.App = window.App || {};

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Minimal, safe Markdown: the text is escaped first, then **bold**, lists,
  // paragraphs and [n] citation markers are turned into HTML. A citation is a
  // link with data-cite="n"; the sources panel decides what clicking it does.
  function answer(text, sourceCount) {
    var inline = function (s) {
      return escapeHtml(s)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\[(\d+)\]/g, function (m, n) {
          n = Number(n);
          if (n < 1 || n > sourceCount) return "";
          return '<a class="cite" href="#src-' + n + '" data-cite="' + n + '" aria-label="source ' + n + '">[' + n + "]</a>";
        });
    };
    var html = "", list = null, para = [];
    function flushPara() { if (para.length) { html += "<p>" + para.map(inline).join(" ") + "</p>"; para = []; } }
    function flushList() { if (list) { html += "<" + list.tag + ">" + list.items.map(function (i) { return "<li>" + inline(i) + "</li>"; }).join("") + "</" + list.tag + ">"; list = null; } }
    String(text).split(/\r?\n/).forEach(function (line) {
      var t = line.trim(), m;
      if (!t) { flushPara(); flushList(); return; }
      if ((m = t.match(/^[-*•]\s+(.*)$/)) || (m = t.match(/^(\d+)[.)]\s+(.*)$/))) {
        var tag = /^\d/.test(t) ? "ol" : "ul";
        var item = m[2] !== undefined ? m[2] : m[1];
        flushPara();
        if (!list || list.tag !== tag) { flushList(); list = { tag: tag, items: [] }; }
        list.items.push(item);
        return;
      }
      flushList();
      para.push(t.replace(/^#+\s*/, ""));
    });
    flushPara(); flushList();
    return html;
  }

  function seconds(ms) { return ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(1) + " s"; }

  App.render = { escapeHtml: escapeHtml, answer: answer, seconds: seconds };
})();
