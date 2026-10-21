// The left panel's document list, grouped by division. selected(targetId)
// returns the document files to search, or null for all of them; DAR-620 adds
// the checkboxes that choose them.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  var box;

  function render(divisions) {
    box = document.getElementById("doc-groups");
    box.innerHTML = divisions.map(function (d) {
      return '<section class="doc-group" data-division="' + R.escapeHtml(d.id) + '"><h3>' + R.escapeHtml(d.name) + "</h3><ul>" +
        d.documents.map(function (doc) {
          return '<li><a href="' + R.escapeHtml(doc.url) + '" target="_blank" rel="noopener">' + R.escapeHtml(doc.title) + "</a></li>";
        }).join("") + "</ul></section>";
    }).join("");
  }

  // The division being asked is the one whose documents are searched.
  function setTarget(targetId) {
    Array.prototype.forEach.call(box.querySelectorAll(".doc-group"), function (g) {
      g.classList.toggle("active", g.getAttribute("data-division") === targetId);
    });
  }

  App.docs = {
    render: render,
    setTarget: setTarget,
    selected: function () { return null; }
  };
})();
