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
  var INTERRUPTED = "The page was reloaded before this question was answered.";
  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var busy = false, answers = 0, askedHere = false;
  var question, thread, newChatBtn, hint;
  // Finished exchanges, oldest first: {question, asker, target, prior, standalone} plus payload or error.
  // prior is the previous question the server searched with (see history()).
  var exchanges = [];
  // The question being answered, stored before it is sent so a reload mid-answer doesn't lose it.
  var pending = null;
  var recordFor = {};  // answerId -> its exchange, for the "Ask … instead" buttons
  var lastTarget = null;      // the division the newest exchange in the thread asked
  var pendingDivider = null;  // "Now asking …" after it while the Ask division is a different one

  function has(obj, key) { return Object.prototype.hasOwnProperty.call(obj, key); }

  // Text goes in through textContent only; the one HTML insert is the answer's own Markdown (R.answer).
  function node(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text != null) n.textContent = text;
    return n;
  }

  function button(className, text, onClick) {
    var b = node("button", className, text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

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

  function scrollTo(target, instant) {
    target.scrollIntoView({ behavior: instant || reduceMotion ? "auto" : "smooth", block: "start" });
  }

  // Changing the division in code reloads its document list (DAR-620), so it is only done when it differs.
  function selectDivisions(askerId, targetId) {
    el("asker").value = askerId;
    if (App.selection().target !== targetId) App.setTarget(targetId);
  }

  function divider(targetId) {
    var d = node("p", "divider");
    d.setAttribute("data-target", targetId);
    d.appendChild(node("span", null, "Now asking " + App.state.byId[targetId].name));
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
    box.textContent = "";
    (division ? division.examples : []).forEach(function (q) {
      // An example is a question of its own, so it goes without the conversation
      // (prefixing the previous question would only blur its search) and starts a new topic.
      box.appendChild(button("chip", q, function () { question.value = q; updateCount(); ask(q, { standalone: true }); }));
    });
    if (thread) targetChanged(division && division.id);
  }

  // One question and its answer. The answer element carries data-answer-id, the
  // key the sources panel keeps that answer's sources under.
  function newExchange(q, answerId, askerId, targetId) {
    var asker = App.state.byId[askerId], target = App.state.byId[targetId];
    var ex = node("article", "exchange card");
    var head = node("p", "result-head", "Answer from ");
    head.appendChild(node("strong", null, target.name));
    if (asker.id !== target.id) head.appendChild(document.createTextNode(", for a colleague in " + asker.name));
    var reply = node("div", "reply");
    reply.setAttribute("data-answer-id", answerId);
    reply.appendChild(node("div", "steps"));
    reply.appendChild(node("div", "answer"));
    ex.appendChild(head);
    ex.appendChild(node("p", "question", q));
    ex.appendChild(reply);
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
      answerEl.textContent = "";
      answerEl.appendChild(node("p", null, data.answer));
      if ((data.suggest || []).length) {
        var box = node("div", "suggest");
        data.suggest.forEach(function (s) {
          var b = button("secondary", "Ask " + s.name + " instead", function () { askInstead(answerId, q, s.id); });
          b.setAttribute("data-suggest", s.id);
          box.appendChild(b);
        });
        answerEl.appendChild(box);
      }
      App.sources.show([], answerId);
    } else {
      answerEl.innerHTML = R.answer(data.answer, data.sources.length);
      App.sources.show(data.sources, answerId);
    }
    var searched = App.docs.searchedNode(data);
    if (searched) answerEl.appendChild(searched);
    steps.finish(data);
  }

  // An error has no sources: the panel is emptied so an older answer's sources don't sit next to it.
  function showError(ex, record) {
    var answerEl = ex.querySelector(".answer");
    ex.classList.add("error");
    answerEl.textContent = "";
    answerEl.appendChild(node("p", null, record.error));
    if (!record.retried) {
      var b = button("secondary retry", "Try again", function () { retry(record, b); });
      answerEl.appendChild(b);
    }
    App.sources.clear();
  }

  // While DAR-629 streams the answer, its text so far, as plain text.
  function showStreaming(answerEl, text) {
    var p = answerEl.querySelector(".streaming");
    if (!p) {
      answerEl.textContent = "";
      p = answerEl.appendChild(node("p", "streaming"));
    }
    p.textContent = text;
  }

  // The options that send a question again the way it was first sent: an example
  // or an "Ask … instead" again without the thread (with the carried question, if any).
  function sameWay(record) {
    var refusedBy = refusedAlready(record);
    if (!record.standalone) return refusedBy.length ? { refusedBy: refusedBy } : null;
    var prior = typeof record.prior === "string" ? record.prior : "";
    return { carry: prior ? [{ question: prior, answer: "" }] : [], refusedBy: refusedBy };
  }

  // The divisions that refused this question before it was asked here; a record
  // restored from an older page has none.
  function refusedAlready(record) {
    return record && Array.isArray(record.refusedBy) ? record.refusedBy : [];
  }

  // The server suggested another division after searching it with the same
  // text as the refused question: the previous question plus this one. Asking
  // there sends that previous question again, without its answer (which came
  // from the first division's documents), so the new search keeps the topic.
  // It also names every division that has refused the question so far, so the
  // new division's refusal doesn't send the visitor back to one of them.
  function askInstead(answerId, q, targetId) {
    if (busy) return;
    var record = recordFor[answerId], prior = record && typeof record.prior === "string" ? record.prior : "";
    var refusedBy = refusedAlready(record).slice();
    if (record && refusedBy.indexOf(record.target) < 0) refusedBy.push(record.target);
    App.setTarget(targetId);
    ask(q, { carry: prior ? [{ question: prior, answer: "" }] : [], refusedBy: refusedBy });
  }

  // "Try again" on a failed exchange: the same question to the same divisions, as a new
  // exchange at the bottom, whatever is in the question box now.
  function retry(record, b) {
    if (busy) return;
    record.retried = true;
    if (b.parentNode) b.parentNode.removeChild(b);
    save();
    selectDivisions(record.asker, record.target);
    ask(record.question, sameWay(record));
  }

  // Draws a finished exchange, live or restored, so both look the same.
  function finish(view, record) {
    if (record.payload) showDone(view.ex, record.question, record.payload, view.answerId, view.steps);
    else showError(view.ex, record);
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
      standalone: !!(options.standalone || options.carry),
      refusedBy: options.refusedBy || []
    };
    var view = addExchange(record);
    pending = record;
    save();
    // The question now shows in the thread; the box is left alone when it holds
    // something else (an "Ask … instead" button re-asks an older question).
    if (question.value.trim() === q) { question.value = ""; updateCount(); }
    // Not "the first question" of a restored thread, but the first since the page loaded,
    // which is the one that may wait for an idle server to start.
    setBusy(true, "Searching the " + target.name + " documents and writing an answer…" +
      (askedHere ? "" : " The first question can take up to a minute while the demo starts."));
    scrollTo(view.ex);
    var streamed = "";
    App.api.ask({
      question: q, asker: sel.asker, target: sel.target,
      history: turns, documents: App.docs.selected(sel.target), refused_by: record.refusedBy
    }, {
      onStep: function (evt) { view.steps.step(evt); },
      onDelta: function (t) { streamed += t; showStreaming(view.answerEl, streamed); },
      onReplace: function (t) { streamed = t; showStreaming(view.answerEl, streamed); },
      onDone: function (data) { record.payload = data; finish(view, record); },
      onError: function (message) {
        record.error = message;
        finish(view, record);
        // Put the question back so it can be sent again without retyping it.
        if (!question.value.trim()) { question.value = q; updateCount(); }
      }
    }).then(settle, settle);

    function settle() {
      pending = null;
      if (record.payload || record.error) exchanges.push(record);
      save();
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
  // "Ask … instead" started a topic, whichever division it asked, so nothing
  // before it counts. [n] markers are dropped because they number the old
  // answer's sources, not the new passages.
  function history() {
    var target = App.selection().target, turns = [];
    for (var i = exchanges.length - 1; i >= 0 && turns.length < HISTORY_TURNS; i--) {
      var x = exchanges[i];
      if (x.target === target && x.payload && !x.payload.refused) {
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
      if (exchanges.length || pending) {
        sessionStorage.setItem(STORE_KEY, JSON.stringify({ exchanges: exchanges.slice(-STORE_EXCHANGES), pending: pending }));
      } else {
        sessionStorage.removeItem(STORE_KEY);
      }
    } catch (e) {
      // An older copy left behind would bring back a thread missing its latest answers.
      try { sessionStorage.removeItem(STORE_KEY); } catch (e2) { /* blocked: nothing was kept */ }
    }
  }

  function load() {
    try {
      var saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null") || {};
      return { exchanges: Array.isArray(saved.exchanges) ? saved.exchanges : [], pending: saved.pending || null };
    } catch (e) {
      return { exchanges: [], pending: null };
    }
  }

  // A stored question from an older page or a division that no longer exists is skipped.
  function knownQuestion(x) {
    return !!x && typeof x.question === "string" && x.question.trim().length >= 3 &&
      has(App.state.byId, x.asker) && has(App.state.byId, x.target);
  }

  function usable(x) {
    if (!knownQuestion(x)) return false;
    if (x.payload) return typeof x.payload.answer === "string" && Array.isArray(x.payload.sources);
    return typeof x.error === "string";
  }

  function clearThread() {
    exchanges = [];
    pending = null;
    recordFor = {};
    lastTarget = null;
    pendingDivider = null;
    thread.textContent = "";
    App.sources.clear();
  }

  function restore() {
    var saved = load(), records = saved.exchanges.filter(usable), p = saved.pending;
    // A question still being answered when the page was reloaded comes back as a
    // failed exchange with Try again, where it was asked.
    if (knownQuestion(p)) {
      records.push({
        question: p.question, asker: p.asker, target: p.target,
        prior: typeof p.prior === "string" ? p.prior : "", standalone: !!p.standalone, error: INTERRUPTED
      });
    }
    if (!records.length) { save(); return; }
    // Drawn quietly: the live region would otherwise read the whole conversation out again.
    thread.setAttribute("aria-live", "off");
    try {
      records.forEach(function (x) {
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
    save();  // the interrupted question is now an ordinary exchange
    var last = records[records.length - 1], lastEx = thread.lastElementChild;
    // app.js picks its default divisions right after init(); this runs once it
    // has, and puts the conversation's divisions back so a follow-up after a
    // reload goes to the same documents with its history.
    Promise.resolve().then(function () {
      selectDivisions(last.asker, last.target);
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

    hint = node("p", "hint followup-hint");
    hint.id = "followup-hint";
    hint.hidden = true;
    question.insertAdjacentElement("afterend", hint);
    question.setAttribute("aria-describedby", "followup-hint");

    newChatBtn = button("secondary new-chat", "New chat", newChat);
    newChatBtn.hidden = true;
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
    fail: function (message) {
      var box = el("thread"), card = node("div", "card error");
      card.appendChild(node("p", null, message));
      box.textContent = "";
      box.appendChild(card);
    }
  };
})();
