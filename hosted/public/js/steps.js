// The steps block above each answer (DAR-629): a "Working…" header while the
// answer is on its way, then "Done in N s" with the model, over the steps on a
// dotted timeline. create(container) returns
//   step(evt)        a live pipeline event {id, label, status: "start"|"done", ms}
//                    (ids: read, search, rerank, write, check, retry, suggest), or
//                    {id: "error", status: "error"} from api.js when the answer failed
//   finish(payload)  the answer is complete (payload as POST api/ask returns it)
// When no step events arrived (the api/ask fallback), finish() shows the steps
// from payload.steps ([{id, label, ms}], the same steps the stream sends). An
// answer that cites no passage gets a visible "No source cited" flag (payload.uncited).
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  var blocks = 0;

  // "nvidia/nemotron-3-ultra-550b-a55b:free" -> "nemotron-3-ultra-550b-a55b"; the full id is the tooltip.
  function modelName(id) { return String(id).replace(/^[^/]*\//, "").replace(/:free$/, ""); }

  // el("span", {class: "x"}, ["text", node]): built with DOM calls, so step labels and
  // model names from the server are only ever text.
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) { node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return node;
  }

  function create(container) {
    var listId = "steps-" + (++blocks);
    var title = el("span", { "class": "steps-title" }, ["Working…"]);
    var meta = el("span", { "class": "steps-meta" });
    var head = el("button", { type: "button", "class": "steps-head", "aria-expanded": "true", "aria-controls": listId }, [
      el("span", { "class": "steps-icon", "aria-hidden": "true" }), title,
      el("span", { "class": "steps-chevron", "aria-hidden": "true" }), meta
    ]);
    var list = el("ol", { "class": "steps-list", id: listId });
    var block = el("div", { "class": "steps-block", "data-state": "running" }, [head, list]);
    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(block);
    var items = {}, toggled = false;
    // The reply around the steps also holds the streamed answer, inside the thread's
    // aria-live region: busy until the end, a screen reader reads the finished answer
    // once instead of every piece of it as it arrives.
    var reply = container.parentNode;
    if (reply) reply.setAttribute("aria-busy", "true");
    function idle() { if (reply) reply.removeAttribute("aria-busy"); }

    function setOpen(open) {
      head.setAttribute("aria-expanded", open ? "true" : "false");
      list.hidden = !open;
    }
    head.addEventListener("click", function () {
      toggled = true; // the visitor's choice wins over the automatic collapse when done
      setOpen(head.getAttribute("aria-expanded") !== "true");
    });

    function item(id, label) {
      var li = items[id];
      if (!li) {
        li = el("li", { "class": "step", "data-step": id }, [el("span", { "class": "step-label" }), el("span", { "class": "step-ms" })]);
        list.appendChild(li);
        items[id] = li;
      }
      if (label) li.querySelector(".step-label").textContent = label;
      return li;
    }

    function mark(li, status, ms) {
      li.setAttribute("data-status", status);
      if (status === "done") li.querySelector(".step-ms").textContent = R.seconds(ms || 0);
    }

    function each(fn) { Object.keys(items).forEach(function (id) { fn(items[id]); }); }

    function stopped() {
      each(function (li) { if (li.getAttribute("data-status") === "running") li.setAttribute("data-status", "failed"); });
      block.setAttribute("data-state", "error");
      title.textContent = "Couldn't finish";
      idle();
    }

    function step(evt) {
      if (!evt || !evt.id || block.getAttribute("data-state") !== "running") return;
      if (evt.status === "error") { stopped(); return; }
      mark(item(evt.id, evt.label), evt.status === "done" ? "done" : "running", evt.ms);
    }

    function finish(payload) {
      payload = payload || {};
      if (!Object.keys(items).length) {
        (payload.steps || []).forEach(function (s) { mark(item(s.id, s.label), "done", s.ms); });
      }
      each(function (li) { if (li.getAttribute("data-status") !== "done") mark(li, "done", 0); });
      block.setAttribute("data-state", "done");
      var total = payload.timing_ms && payload.timing_ms.total;
      title.textContent = typeof total === "number" ? "Done in " + R.seconds(total) : "Done";
      if (payload.model) {
        var text = modelName(payload.model), tip = payload.model;
        if (payload.retried && payload.first_model) {
          text += ", retried after " + modelName(payload.first_model);
          tip += " (retried after " + payload.first_model + ")";
        }
        meta.textContent = text;
        meta.title = tip;
      }
      if (payload.uncited) {
        container.appendChild(el("p", { "class": "uncited-flag" }, [
          el("strong", {}, ["No source cited."]),
          " This answer doesn't point to a page of the documents, so check it there before relying on it."
        ]));
      }
      if (!toggled) setOpen(false);
      idle();
    }

    return { step: step, finish: finish };
  }

  App.steps = { create: create };
})();
