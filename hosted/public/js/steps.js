// The steps block above each answer (DAR-629): a "Working…" header while the
// answer is on its way, then "Done in N s" with the model, over the steps on a
// dotted timeline. create(container) returns
//   step(evt)        a live pipeline event {id, label, status: "pending"|"start"|"done", ms}
//                    (ids: read, search, rerank, write, check, retry, suggest), or
//                    {id: "error", status: "error"} from api.js when the answer failed
//   finish(payload)  the answer is complete (payload as POST api/ask returns it)
// The stream first lists the steps expected to run as "pending" (DAR-636), so each
// step shows one of three icons: a gray hollow circle (not started), a solid circle
// (in progress) and a check mark (done); a step the answer stopped on is "failed".
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

  // Read before each label, as the icons alone say nothing to a screen reader.
  var STATUS_TEXT = { pending: "Not started: ", running: "In progress: ", done: "Done: ", failed: "Stopped: " };

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
        li = el("li", { "class": "step", "data-step": id }, [
          el("span", { "class": "step-sr" }), el("span", { "class": "step-label" }), el("span", { "class": "step-ms" })
        ]);
        list.appendChild(li);
        items[id] = li;
      }
      if (label) li.querySelector(".step-label").textContent = label;
      return li;
    }

    function mark(li, status, ms) {
      li.setAttribute("data-status", status);
      li.querySelector(".step-sr").textContent = STATUS_TEXT[status];
      if (status === "done") li.querySelector(".step-ms").textContent = R.seconds(ms || 0);
    }

    function each(fn) { Object.keys(items).forEach(function (id) { fn(items[id], id); }); }

    // A step that hadn't started stays "not started": only the one it was on stopped.
    function stopped() {
      each(function (li) { if (li.getAttribute("data-status") === "running") mark(li, "failed"); });
      block.setAttribute("data-state", "error");
      title.textContent = "Couldn't finish";
      idle();
    }

    function step(evt) {
      if (!evt || !evt.id || block.getAttribute("data-state") !== "running") return;
      if (evt.status === "error") { stopped(); return; }
      var li = item(evt.id, evt.label);
      if (evt.status === "pending") {
        if (!li.getAttribute("data-status")) mark(li, "pending"); // never back from running or done
        return;
      }
      skippedBefore(li);
      mark(li, evt.status === "done" ? "done" : "running", evt.ms);
    }

    function drop(li) {
      list.removeChild(li);
      delete items[li.getAttribute("data-step")];
    }

    // The steps run in the order listed, so one still pending before a step that started
    // was skipped (the reranker skips a search that found a single passage): it leaves the
    // list, instead of staying "not started" while later steps run, or after an error.
    function skippedBefore(li) {
      for (var n = list.firstChild, next; n && n !== li; n = next) {
        next = n.nextSibling;
        if (n.getAttribute("data-status") === "pending") drop(n);
      }
    }

    function finish(payload) {
      payload = payload || {};
      var finished = {};
      (payload.steps || []).forEach(function (s) { finished[s.id] = s; });
      if (!Object.keys(items).length) {
        (payload.steps || []).forEach(function (s) { mark(item(s.id, s.label), "done", s.ms); });
      }
      // Only a step that ran is shown done; one still pending never started and leaves
      // the list, so the finished list is the payload's steps, as after the api/ask fallback.
      each(function (li, id) {
        var status = li.getAttribute("data-status"), s = finished[id];
        if (status === "done") return;
        if (status === "running" || s) mark(li, "done", s ? s.ms : 0);
        else drop(li);
      });
      block.setAttribute("data-state", "done");
      var total = payload.timing_ms && payload.timing_ms.total;
      title.textContent = typeof total === "number" ? "Done in " + R.seconds(total) : "Done";
      if (payload.model) {
        var text = modelName(payload.model), tip = payload.model;
        // `model` gave the final reply. The same model again means the retry's call
        // failed (or the last fallback model was asked twice), so there is no "after".
        if (payload.retried && payload.first_model && payload.first_model !== payload.model) {
          text += ", retried after " + modelName(payload.first_model);
          tip += " (retried after " + payload.first_model + ")";
        } else if (payload.retried) {
          text += ", retried";
          tip += " (retried)";
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
