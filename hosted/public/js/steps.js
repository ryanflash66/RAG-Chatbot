// The progress block above each answer. create(container) returns
//   step(evt)        a live pipeline event {id, label, status: "start"|"done", ms}
//                    (ids: read, search, rerank, write, check, retry, suggest)
//   finish(payload)  the answer is complete (payload as POST api/ask returns it)
// Until DAR-629 streams events, step() does nothing and finish() shows the
// model and the time per step from payload.timing_ms.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;

  // timing_ms keys from hosted/divrag/timing.py, in pipeline order.
  var STEP_LABELS = [
    ["model_load", "Loading the search models"],
    ["embed", "Reading the question"],
    ["search", "Searching the documents"],
    ["rerank", "Reranking the passages"],
    ["llm", "Writing the answer"],
    ["citations", "Checking the citations"],
    ["retry", "Retrying with another model"],
    ["suggest", "Checking the other divisions"]
  ];
  var OPTIONAL_STEPS = { retry: true, suggest: true };

  function timingHtml(data) {
    var t = data.timing_ms;
    if (!t) return "";
    var line = '<p class="model">' + (data.model && !data.refused ? "Written by " + R.escapeHtml(data.model) + " in " : "Answered in ") +
      R.seconds(t.total) + (data.retried && data.first_model ? " (retried after " + R.escapeHtml(data.first_model) + ")" : "") + ".</p>";
    var rows = STEP_LABELS.filter(function (s) {
      return typeof t[s[0]] === "number" && !(OPTIONAL_STEPS[s[0]] && !t[s[0]]);
    }).map(function (s) {
      return "<tr><td>" + s[1] + "</td><td>" + R.seconds(t[s[0]]) + "</td></tr>";
    }).join("");
    return line + '<details><summary>Time per step</summary><table class="timing">' + rows +
      '<tr class="total"><td>Total</td><td>' + R.seconds(t.total) + "</td></tr></table></details>";
  }

  function create(container) {
    return {
      step: function () {},
      finish: function (payload) { container.innerHTML = timingHtml(payload); }
    };
  }

  App.steps = { create: create };
})();
