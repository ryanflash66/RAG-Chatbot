// Calls to the server. ask() is the contract the chat relies on; DAR-629 swaps
// its body for the streaming endpoint (POST api/ask/stream, server-sent events)
// without changing its shape:
//   request  {question, asker, target, history: [{question, answer}], documents: [file] | null}
//   handlers {onStep(evt), onDelta(text), onReplace(text), onDone(payload), onError(message)}
// payload is the JSON POST api/ask returns. Exactly one of onDone and onError is
// called, and the returned promise settles after it.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var UNREACHABLE = "Couldn't reach the server. Check your connection and try again.";

  function divisions() {
    return fetch("api/divisions").then(function (r) { return r.json(); });
  }

  function warm() {
    return fetch("api/warm", { method: "POST" });
  }

  function ask(request, handlers) {
    return fetch("api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    }).then(function (res) {
      var unexpected = "The server returned an unexpected response (" + res.status + ").";
      return res.json().catch(function () { return {}; }).then(function (data) {
        // Our errors arrive as {error}; FastAPI's own validation errors (422) as {detail}.
        // Anything that isn't an answer is an error, so the chat never waits on a broken reply.
        if (data.error) return data;
        return res.ok && typeof data.answer === "string" ? data : { error: unexpected };
      });
    }).then(function (data) {
      if (data.error) handlers.onError(data.error);
      else handlers.onDone(data);
    }, function () {
      handlers.onError(UNREACHABLE);
    });
  }

  App.api = { divisions: divisions, warm: warm, ask: ask };
})();
