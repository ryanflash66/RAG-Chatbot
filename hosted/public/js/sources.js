// The right panel: the passages an answer cites. show() keeps each answer's
// sources under its id (the data-answer-id of its message), so the panel can be
// switched back to an older answer when one of its [n] citations is clicked (DAR-627).
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  var EMPTY = '<p class="empty">The passages an answer uses appear here, with a link to each PDF page.</p>';
  var byAnswer = {};
  var box;

  function itemHtml(s) {
    var meta = [];
    if (s.page) meta.push(s.page_end && s.page_end !== s.page ? "PDF pages " + s.page + "–" + s.page_end : "PDF page " + s.page);
    if (s.section) meta.push("Section " + R.escapeHtml(s.section));
    var link = s.url
      ? '<a class="src-link" href="' + R.escapeHtml(s.url) + '" target="_blank" rel="noopener">Open the PDF at this page</a>'
      : "";
    return '<li id="src-' + s.n + '"><span class="src-n">[' + s.n + ']</span>' +
      '<span class="src-title">' + R.escapeHtml(s.title) + "</span>" +
      '<div class="src-meta">' + meta.join(" · ") + "</div>" + link +
      "<details><summary>Show the passage used</summary><blockquote>" + R.escapeHtml(s.excerpt) + "</blockquote></details></li>";
  }

  function render(sources) {
    box.innerHTML = sources && sources.length
      ? '<ol class="sources">' + sources.map(itemHtml).join("") + "</ol>"
      : '<p class="empty">This answer has no sources.</p>';
  }

  App.sources = {
    init: function () { box = document.getElementById("sources"); box.innerHTML = EMPTY; },
    show: function (sources, answerId) { byAnswer[answerId] = sources || []; render(sources); },
    clear: function () { box.innerHTML = EMPTY; }
  };
})();
