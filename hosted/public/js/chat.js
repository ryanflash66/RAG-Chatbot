// The middle panel: example questions, the conversation and the question box.
// Every exchange stays in #thread, oldest first, with the question box below
// it, so Dr. Namian can ask follow-ups. The thread is kept in sessionStorage
// (each question with its final payload) and a reload draws it again through
// the same code as a live answer. history() is what a follow-up sends.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var R = App.render;
  var el = function (id) { return document.getElementById(id); };
  // A follow-up carries the last few answered turns; the server keeps only 3 as well.
  var HISTORY_TURNS = 3;
  // An earlier answer only shows what "it" refers to (the facts come from the new
  // passages), so a long one is clipped; the server's limit per answer is 4,000.
  var HISTORY_ANSWER_CHARS = 1500;
  // One tab's conversation: sessionStorage survives a reload and is gone when the tab closes.
  var STORE_KEY = "ncdot-qa-thread-v1";
  // A payload with its sources is a few kB; sessionStorage holds about 5 MB per site.
  var STORE_EXCHANGES = 40;
  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var busy = false, answers = 0, askedHere = false;
  var question, thread, newChatBtn, hint;
  // Finished exchanges, oldest first: {question, asker, target, prior, standalone} plus payload or error.
  // prior is the previous question the server searched with (see history()).
  var exchanges = [];
  var recordFor = {};  // answerId -> its exchange, for the "Ask … instead" buttons
  var lastTarget = null;      // the division the newest exchange in the thread asked
  var pendingDivider = null;  // "Now asking …" after it while the Ask division is a different one

  function has(obj, key) { return Object.prototype.hasOwnProperty.call(obj, key); }

  function updateCount() {
    var n = question.value.length, max = App.state.maxChars;
    el("count").textContent = n > max * 0.8 ? n + " / " + max : "";
  }

  function setBusy(on, text) {
    busy = on;
    el("ask-btn").disabled = on;
    newChatBtn.disabled = on;
    el("status").hidden = !on;
    el("status-text").textContent = text || "";
  }

  // New chat appears once there is something to clear; the hint says when a
  // question will be read as a follow-up, because the search then includes the previous question.
  function refresh() {
    newChatBtn.hidden = !exchanges.length;
    var target = App.state.byId[App.selection().target], show = !!(target && history().length);
    hint.hidden = !show;
    // Emptied when hidden: the question box's aria-describedby would still read hidden text.
    hint.textContent = show ? "Read as a follow-up to your last " + target.name +
      " question. For a new topic, start a new chat." : "";
  }

  function scrollTo(node, instant) {
    node.scrollIntoView({ behavior: instant || reduceMotion ? "auto" : "smooth", block: "start" });
  }

  function divider(targetId) {
    var d = document.createElement("p");
    d.className = "divider";
    d.setAttribute("data-target", targetId);
    d.innerHTML = "<span>Now asking " + R.escapeHtml(App.state.byId[targetId].name) + "</span>";
    return d;
  }

  // The Ask division changed: a divider after the newest exchange shows that the
  // next answer comes from other documents, and goes again if the change is undone.
  function targetChanged(targetId) {
    if (pendingDivider) { thread.removeChild(pendingDivider); pendingDivider = null; }
    if (lastTarget && targetId && targetId !== lastTarget && has(App.state.byId, targetId)) {
      pendingDivider = divider(targetId);
      thread.appendChild(pendingDivider);
    }
    refresh();
  }

  // app.js calls this whenever the Ask division changes, including on start.
  function showExamples(division) {
    el("examples-label").textContent = "Try an example question for " + (division ? division.name : "") + ":";
    var box = el("examples");
    box.innerHTML = "";
    (division ? division.examples : []).forEach(function (q) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = q;
      // An example is a question of its own, so it goes without the conversation
      // (prefixing the previous question would only blur its search) and starts a new topic.
      b.addEventListener("click", function () { question.value = q; updateCount(); ask(q, { standalone: true }); });
      box.appendChild(b);
    });
    if (thread) targetChanged(division && division.id);
  }

  // One question and its answer. The answer element carries data-answer-id, the
  // key the sources panel keeps that answer's sources under.
  function newExchange(q, answerId, askerId, targetId) {
    var asker = App.state.byId[askerId], target = App.state.byId[targetId];
    var ex = document.createElement("article");
    ex.className = "exchange card";
    ex.innerHTML = '<p class="result-head">Answer from <strong>' + R.escapeHtml(target.name) + "</strong>" +
      (asker.id !== target.id ? ", for a colleague in " + R.escapeHtml(asker.name) : "") + "</p>" +
      '<p class="question">' + R.escapeHtml(q) + "</p>" +
      '<div class="reply" data-answer-id="' + answerId + '"><div class="steps"></div><div class="answer"></div></div>';
    return ex;
  }

  // Appends an exchange to the thread, after a divider when it asks another division than the one before.
  function addExchange(record) {
    var answerId = "a" + (++answers);
    var ex = newExchange(record.question, answerId, record.asker, record.target);
    recordFor[answerId] = record;
    if (pendingDivider && pendingDivider.getAttribute("data-target") !== record.target) {
      thread.removeChild(pendingDivider);
      pendingDivider = null;
    }
    if (lastTarget && record.target !== lastTarget && !pendingDivider) thread.appendChild(divider(record.target));
    pendingDivider = null;  // it now belongs to the thread
    lastTarget = record.target;
    thread.appendChild(ex);
    return { ex: ex, answerId: answerId, answerEl: ex.querySelector(".answer"), steps: App.steps.create(ex.querySelector(".steps")) };
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
        b.addEventListener("click", function () { askInstead(answerId, q, b.getAttribute("data-suggest")); });
      });
      App.sources.show([], answerId);
    } else {
      answerEl.innerHTML = R.answer(data.answer, data.sources.length);
      App.sources.show(data.sources, answerId);
    }
    steps.finish(data);
  }

  function showError(ex, message) {
    ex.classList.add("error");
    ex.querySelector(".answer").innerHTML = "<p>" + R.escapeHtml(message) + "</p>";
  }

  // The server suggested the other division after searching it with the same
  // text as the refused question: the previous question plus this one. Asking
  // there sends that previous question again, without its answer (which came
  // from the first division's documents), so the new search keeps the topic.
  function askInstead(answerId, q, targetId) {
    if (busy) return;
    var record = recordFor[answerId], prior = record && typeof record.prior === "string" ? record.prior : "";
    App.setTarget(targetId);
    ask(q, { carry: prior ? [{ question: prior, answer: "" }] : [] });
  }

  // Draws a finished exchange, live or restored, so both look the same.
  function finish(view, record) {
    if (record.payload) showDone(view.ex, record.question, record.payload, view.answerId, view.steps);
    else showError(view.ex, record.error);
  }

  function ask(text, options) {
    if (busy) return;
    var q = String(text == null ? question.value : text).trim();
    if (q.length < 3) { question.focus(); return; }
    options = options || {};
    var sel = App.selection(), target = App.state.byId[sel.target];
    // standalone: no earlier turns; carry: these turns instead of the thread's. Either way the
    // exchange starts a topic, and later follow-ups look no further back than it.
    var turns = options.standalone ? [] : options.carry || history();
    var record = {
      question: q, asker: sel.asker, target: sel.target,
      prior: turns.length ? turns[turns.length - 1].question : "",
      standalone: !!(options.standalone || options.carry)
    };
    var view = addExchange(record);
    var answerEl = view.answerEl;
    var streamed = "";
    // The question now shows in the thread; the box is left alone when it holds
    // something else (an "Ask … instead" button re-asks an older question).
    if (question.value.trim() === q) { question.value = ""; updateCount(); }
    // Not "the first question" of a restored thread, but the first since the page loaded,
    // which is the one that may wait for an idle server to start.
    setBusy(true, "Searching the " + target.name + " documents and writing an answer…" +
      (askedHere ? "" : " The first question can take up to a minute while the demo starts."));
    scrollTo(view.ex);
    App.api.ask({
      question: q, asker: sel.asker, target: sel.target,
      history: turns, documents: App.docs.selected(sel.target)
    }, {
      onStep: function (evt) { view.steps.step(evt); },
      onDelta: function (t) { streamed += t; answerEl.innerHTML = '<p class="streaming">' + R.escapeHtml(streamed) + "</p>"; },
      onReplace: function (t) { streamed = t; answerEl.innerHTML = '<p class="streaming">' + R.escapeHtml(streamed) + "</p>"; },
      onDone: function (data) { record.payload = data; finish(view, record); },
      onError: function (message) {
        record.error = message;
        finish(view, record);
        // Put the question back so it can be sent again without retyping it.
        if (!question.value.trim()) { question.value = q; updateCount(); }
      }
    }).then(settle, settle);

    function settle() {
      if (record.payload || record.error) { exchanges.push(record); save(); }
      askedHere = true;
      setBusy(false);
      refresh();
    }
  }

  function stripCitations(text) { return String(text).replace(/\s*\[\d+\]/g, ""); }

  function clip(text, max) {
    text = text.replace(/[ \t]+/g, " ").trim();
    if (text.length <= max) return text;
    var cut = text.slice(0, max), space = cut.lastIndexOf(" ");
    return (space > max * 0.8 ? cut.slice(0, space) : cut) + " …";
  }

  // The earlier exchanges to send with a question, oldest first: [{question, answer}].
  // Only answered turns with the division being asked count: a refusal or an
  // error holds nothing to refer back to, and another division's answer came
  // from documents this question won't search. An example question or an
  // "Ask … instead" started a topic, so nothing before it counts. [n] markers are
  // dropped because they number the old answer's sources, not the new passages.
  function history() {
    var target = App.selection().target, turns = [];
    for (var i = exchanges.length - 1; i >= 0 && turns.length < HISTORY_TURNS; i--) {
      var x = exchanges[i];
      if (x.target !== target) continue;
      if (x.payload && !x.payload.refused) {
        turns.unshift({ question: x.question, answer: clip(stripCitations(x.payload.answer), HISTORY_ANSWER_CHARS) });
      }
      if (x.standalone) break;
    }
    return turns;
  }

  // Storage can be full, blocked or disabled (private windows); the thread then
  // works as usual and just isn't there after a reload.
  function save() {
    try {
      if (exchanges.length) sessionStorage.setItem(STORE_KEY, JSON.stringify({ exchanges: exchanges.slice(-STORE_EXCHANGES) }));
      else sessionStorage.removeItem(STORE_KEY);
    } catch (e) {
      // An older copy left behind would bring back a thread missing its latest answers.
      try { sessionStorage.removeItem(STORE_KEY); } catch (e2) { /* blocked: nothing was kept */ }
    }
  }

  function load() {
    try {
      var saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
      return saved && Array.isArray(saved.exchanges) ? saved.exchanges : [];
    } catch (e) {
      return [];
    }
  }

  // A stored exchange from an older page or a division that no longer exists is skipped.
  function usable(x) {
    if (!x || typeof x.question !== "string" || !has(App.state.byId, x.asker) || !has(App.state.byId, x.target)) return false;
    if (x.payload) return typeof x.payload.answer === "string" && Array.isArray(x.payload.sources);
    return typeof x.error === "string";
  }

  function clearThread() {
    exchanges = [];
    recordFor = {};
    lastTarget = null;
    pendingDivider = null;
    thread.innerHTML = "";
    App.sources.clear();
  }

  function restore() {
    var saved = load().filter(usable);
    if (!saved.length) return;
    // Drawn quietly: the live region would otherwise read the whole conversation out again.
    thread.setAttribute("aria-live", "off");
    try {
      saved.forEach(function (x) {
        finish(addExchange(x), x);
        exchanges.push(x);
      });
    } catch (e) {
      clearThread();
      save();
      return;
    } finally {
      thread.setAttribute("aria-live", "polite");
    }
    var last = saved[saved.length - 1], lastEx = thread.lastElementChild;
    // app.js picks its default divisions right after init(); this runs once it
    // has, and puts the conversation's divisions back so a follow-up after a
    // reload goes to the same documents with its history.
    Promise.resolve().then(function () {
      el("asker").value = last.asker;
      App.setTarget(last.target);
      scrollTo(lastEx, true);
    });
  }

  function newChat() {
    if (busy) return;
    clearThread();
    save();
    refresh();
    question.focus();
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

    hint = document.createElement("p");
    hint.className = "hint followup-hint";
    hint.id = "followup-hint";
    hint.hidden = true;
    question.insertAdjacentElement("afterend", hint);
    question.setAttribute("aria-describedby", "followup-hint");

    newChatBtn = document.createElement("button");
    newChatBtn.type = "button";
    newChatBtn.className = "secondary new-chat";
    newChatBtn.textContent = "New chat";
    newChatBtn.hidden = true;
    newChatBtn.addEventListener("click", newChat);
    el("ask-btn").insertAdjacentElement("afterend", newChatBtn);

    restore();
    refresh();
  }

  App.chat = {
    init: init,
    ask: ask,
    newChat: newChat,
    showExamples: showExamples,
    history: history,
    // Shown in the thread when the demo can't start.
    fail: function (message) { el("thread").innerHTML = '<div class="card error"><p>' + R.escapeHtml(message) + "</p></div>"; }
  };
})();
