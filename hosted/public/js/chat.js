// The middle panel: example questions, the conversation and the question box.
// Until DAR-619, the thread holds only the latest exchange and history() is empty.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  var el = function (id) { return document.getElementById(id); };
  var busy = false, answers = 0;
  var question, thread;

  function updateCount() {
    var n = question.value.length, max = App.state.maxChars;
    el("count").textContent = n > max * 0.8 ? n + " / " + max : "";
  }

  function setBusy(on, text) {
    busy = on;
    el("ask-btn").disabled = on;
    el("status").hidden = !on;
    el("status-text").textContent = text || "";
  }

  function showExamples(division) {
    el("examples-label").textContent = "Try an example question for " + (division ? division.name : "") + ":";
    var box = el("examples");
    box.innerHTML = "";
    (division ? division.examples : []).forEach(function (q) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = q;
      b.addEventListener("click", function () { question.value = q; updateCount(); ask(q); });
      box.appendChild(b);
    });
  }

  // One question and its answer. The answer element carries data-answer-id, the
  // key the sources panel keeps that answer's sources under.
  function newExchange(q, answerId) {
    var sel = App.selection(), asker = App.state.byId[sel.asker], target = App.state.byId[sel.target];
    var ex = document.createElement("article");
    ex.className = "exchange card";
    ex.innerHTML = '<p class="result-head">Answer from <strong>' + R.escapeHtml(target.name) + "</strong>" +
      (asker.id !== target.id ? ", for a colleague in " + R.escapeHtml(asker.name) : "") + "</p>" +
      '<p class="question">' + R.escapeHtml(q) + "</p>" +
      '<div class="reply" data-answer-id="' + answerId + '"><div class="steps"></div><div class="answer"></div></div>';
    return ex;
  }

  function showDone(ex, q, data, answerId, steps) {
    var answerEl = ex.querySelector(".answer");
    if (data.refused) {
      ex.classList.add("notice");
      var html = "<p>" + R.escapeHtml(data.answer) + "</p>";
      if ((data.suggest || []).length) {
        html += '<div class="suggest">' + data.suggest.map(function (s) {
          return '<button type="button" class="secondary" data-suggest="' + R.escapeHtml(s.id) + '">Ask ' + R.escapeHtml(s.name) + " instead</button>";
        }).join("") + "</div>";
      }
      answerEl.innerHTML = html;
      Array.prototype.forEach.call(answerEl.querySelectorAll("[data-suggest]"), function (b) {
        b.addEventListener("click", function () { App.setTarget(b.getAttribute("data-suggest")); ask(q); });
      });
      App.sources.show([], answerId);
    } else {
      answerEl.innerHTML = R.answer(data.answer, data.sources.length);
      App.sources.show(data.sources, answerId);
    }
    answerEl.insertAdjacentHTML("beforeend", App.docs.searchedHtml(data));
    steps.finish(data);
  }

  function ask(text) {
    if (busy) return;
    var q = String(text == null ? question.value : text).trim();
    if (q.length < 3) { question.focus(); return; }
    var sel = App.selection(), target = App.state.byId[sel.target];
    var answerId = "a" + (++answers);
    var ex = newExchange(q, answerId);
    thread.innerHTML = "";
    thread.appendChild(ex);
    var answerEl = ex.querySelector(".answer");
    var steps = App.steps.create(ex.querySelector(".steps"));
    var streamed = "";
    setBusy(true, "Searching the " + target.name + " documents and writing an answer… The first question can take up to a minute while the demo starts.");
    App.api.ask({
      question: q, asker: sel.asker, target: sel.target,
      history: App.chat.history(), documents: App.docs.selected(sel.target)
    }, {
      onStep: function (evt) { steps.step(evt); },
      onDelta: function (t) { streamed += t; answerEl.innerHTML = '<p class="streaming">' + R.escapeHtml(streamed) + "</p>"; },
      onReplace: function (t) { streamed = t; answerEl.innerHTML = '<p class="streaming">' + R.escapeHtml(streamed) + "</p>"; },
      onDone: function (data) { showDone(ex, q, data, answerId, steps); },
      onError: function (message) { ex.classList.add("error"); answerEl.innerHTML = "<p>" + R.escapeHtml(message) + "</p>"; }
    }).then(function () {
      setBusy(false);
      ex.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function init() {
    question = el("question");
    thread = el("thread");
    question.maxLength = App.state.maxChars;
    question.addEventListener("focus", App.warmUp);
    question.addEventListener("input", function () { updateCount(); App.warmUp(); });
    question.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ask(); }
    });
    el("ask-form").addEventListener("submit", function (e) { e.preventDefault(); ask(); });
  }

  App.chat = {
    init: init,
    ask: ask,
    showExamples: showExamples,
    // The earlier exchanges to send with a question, oldest first: [{question, answer}].
    history: function () { return []; },
    // Shown in the thread when the demo can't start.
    fail: function (message) { el("thread").innerHTML = '<div class="card error"><p>' + R.escapeHtml(message) + "</p></div>"; }
  };
})();
