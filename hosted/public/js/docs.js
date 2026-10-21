// The left panel's document list, grouped by division, under the pickers. The
// division being asked comes first, and its documents have checkboxes that choose
// which of them the next question searches; the other divisions' documents are
// listed read-only, because answers come only from the asked division's documents.
// Nothing can be added or deleted here. selected(targetId) returns the ticked
// files, or null when all are ticked; searchedHtml(payload) is the "Searched N
// passages in M documents" line under each answer.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  // Shows the Upload button only. It is not access control: there are no accounts or roles
  // yet (per Dr. Namian), so the team opens the page with ?team=1.
  var TEAM = /(?:^|[?&])team=1(?:&|$)/.test(window.location.search);
  var box, divisions = [], byId = {}, targetId = null;
  // Unticked documents per division, {divisionId: {file: true}}; everything else is ticked.
  // Kept across target switches, so going back to a division keeps its choice.
  var unticked = {};
  // The visitor tried to untick the last ticked document; the hint says why it stayed ticked.
  var keptLast = false;

  function count(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  function documentsText(n, total) {
    return n < total ? n + " of " + total + " documents" : count(n, "document");
  }

  function isTicked(divisionId, file) {
    return !(unticked[divisionId] && unticked[divisionId][file]);
  }

  function ticked(d) {
    return d.documents.filter(function (doc) { return isTicked(d.id, doc.file); });
  }

  // Why the last ticked document can't be unticked: a question has to search something
  // (the server answers an empty list with "Pick at least one document to search.").
  function keptReason(d) {
    return d.documents.length === 1
      ? d.name + " has one document for now, so it is always searched."
      : "At least one document has to be searched.";
  }

  function hintText(d) {
    if (keptLast || d.documents.length === 1) return keptReason(d);
    return "Untick a document to leave it out of the search.";
  }

  function summaryText(d) {
    var picks = ticked(d);
    // All ticked sends no list, and the server then searches every passage of the division.
    var passages = picks.length === d.documents.length ? d.passages
      : picks.reduce(function (n, doc) { return n + doc.passages; }, 0);
    if (typeof passages !== "number" || isNaN(passages)) return "";
    return "Searches " + count(passages, "passage") + " in " + documentsText(picks.length, d.documents.length) + ".";
  }

  // Builds elements with DOM calls rather than HTML strings, so names, files and links
  // from /api/divisions are only ever text and attribute values, never parsed as markup.
  function h(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "checked") node.checked = node.defaultChecked = !!attrs[k];
      else if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === "") return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function metaNode(doc) {
    var parts = [];
    if (typeof doc.passages === "number") parts.push(count(doc.passages, "passage"));
    if (doc.url) parts.push(h("a", { href: doc.url, target: "_blank", rel: "noopener" }, ["Open the PDF"]));
    if (!parts.length) return null;
    var children = [];
    parts.forEach(function (part, i) { if (i) children.push(" · "); children.push(part); });
    return h("div", { "class": "doc-meta" }, children);
  }

  function activeNode(d) {
    // The group role sits on the section, not the list, so the <li>s stay a list for screen readers.
    return h("section", { "class": "doc-group active", "data-division": d.id, role: "group", "aria-labelledby": "docs-asked" }, [
      h("h3", { id: "docs-asked" }, [h("span", { "class": "doc-state" }, ["Asking"]), " " + d.name]),
      h("p", { "class": "doc-summary" }),
      h("ul", { "class": "doc-list" }, d.documents.map(function (doc) {
        return h("li", { "class": "doc" }, [
          h("label", { "class": "doc-pick" }, [
            h("input", { type: "checkbox", "data-file": doc.file, checked: isTicked(d.id, doc.file) }),
            h("span", { "class": "doc-title" }, [doc.title])
          ]),
          metaNode(doc)
        ]);
      })),
      h("p", { "class": "hint", id: "docs-hint" })
    ]);
  }

  // "Not asked" rather than "Not searched": after a refusal the server does look through
  // the other divisions, but only to suggest asking one of them instead (answer.py).
  function otherNode(d) {
    return h("section", { "class": "doc-group", "data-division": d.id }, [
      h("h3", {}, [h("span", { "class": "doc-state" }, ["Not asked"]), " " + d.name]),
      h("ul", { "class": "doc-list" }, d.documents.map(function (doc) {
        return h("li", { "class": "doc" }, [h("span", { "class": "doc-title" }, [doc.title]), metaNode(doc)]);
      }))
    ]);
  }

  // Updates the asked division's group in place (not redrawn), so a keyboard user keeps focus on the checkbox.
  function refresh() {
    var d = byId[targetId], group = box && box.querySelector(".doc-group.active");
    if (!d || !group) return;
    var sole = ticked(d).length === 1, reason = keptReason(d);
    // The last ticked box is aria-disabled rather than disabled: it looks fixed, but stays
    // focusable and keeps its hover title, so keyboard and mouse users can still find out why.
    Array.prototype.forEach.call(group.querySelectorAll("input[data-file]"), function (cb) {
      var kept = sole && cb.checked;
      if (kept) {
        cb.parentNode.title = reason;  // on the label, so hovering the document's title shows it too
        cb.setAttribute("aria-describedby", "docs-hint");
        cb.setAttribute("aria-disabled", "true");
      } else {
        cb.parentNode.removeAttribute("title");
        cb.removeAttribute("aria-describedby");
        cb.removeAttribute("aria-disabled");
      }
    });
    group.querySelector(".doc-summary").textContent = summaryText(d);
    var hint = group.querySelector(".hint");
    hint.textContent = hintText(d);
    hint.classList.toggle("warn", keptLast);
  }

  function draw() {
    var d = byId[targetId];
    var groups = (d ? [activeNode(d)] : []).concat(divisions.filter(function (o) { return o !== d; }).map(otherNode));
    while (box.firstChild) box.removeChild(box.firstChild);
    groups.forEach(function (g) { box.appendChild(g); });
    refresh();
  }

  function onChange(e) {
    var cb = e.target, d = byId[targetId];
    var file = cb.getAttribute ? cb.getAttribute("data-file") : null;
    if (file === null || !d) return;
    var others = ticked(d).filter(function (doc) { return doc.file !== file; });
    if (!cb.checked && !others.length) {
      cb.checked = true;
      keptLast = true;
    } else {
      unticked[d.id] = unticked[d.id] || {};
      if (cb.checked) delete unticked[d.id][file];
      else unticked[d.id][file] = true;
      keptLast = false;
    }
    refresh();
  }

  // Team only, and it uploads nothing: documents are fixed in divisions.py until the
  // document database (DAR-621) lets the team add them.
  function addUploadButton() {
    if (!TEAM || document.getElementById("upload-docs")) return;
    var button = h("button", { type: "button", "class": "secondary", id: "upload-docs", "aria-expanded": "false", "aria-controls": "upload-note" },
      ["Upload documents"]);
    var note = h("p", { "class": "hint", id: "upload-note" },
      ["Uploading comes with the document database (DAR-621). Nothing is uploaded from here yet."]);
    note.hidden = true;
    var tools = h("div", { "class": "doc-tools" }, [button, h("span", { "class": "doc-state" }, ["Team only"]), note]);
    box.parentNode.insertBefore(tools, box.nextSibling);
    button.addEventListener("click", function () {
      note.hidden = !note.hidden;
      button.setAttribute("aria-expanded", String(!note.hidden));
    });
  }

  function render(list) {
    divisions = list || [];
    byId = {};
    divisions.forEach(function (d) { byId[d.id] = d; });
    box = document.getElementById("doc-groups");
    box.addEventListener("change", onChange);
    draw();
    addUploadButton();
  }

  // The division being asked is the one whose documents are searched.
  function setTarget(id) {
    targetId = id;
    keptLast = false;
    if (box) draw();
  }

  function selected(id) {
    var d = byId[id];
    if (!d) return null;
    var picks = ticked(d);
    return picks.length === d.documents.length ? null : picks.map(function (doc) { return doc.file; });
  }

  // payload is the JSON POST api/ask returns; "" when it has no searched counts.
  function searchedHtml(payload) {
    var s = payload && payload.searched;
    if (!s || typeof s.passages !== "number" || typeof s.documents !== "number") return "";
    var d = payload.target && byId[payload.target.id];
    var total = d ? d.documents.length : s.documents;
    return '<p class="searched">' +
      R.escapeHtml("Searched " + count(s.passages, "passage") + " in " + documentsText(s.documents, total) + ".") + "</p>";
  }

  App.docs = {
    render: render,
    setTarget: setTarget,
    selected: selected,
    searchedHtml: searchedHtml
  };
})();
