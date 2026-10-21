// Calls to the server. ask() is the contract the chat relies on:
//   request  {question, asker, target, history: [{question, answer}], documents: [file] | null}
//   handlers {onStep(evt), onDelta(text), onReplace(text), onDone(payload), onError(message)}
// payload is the JSON POST api/ask returns. Exactly one of onDone and onError is
// called, and the returned promise settles after it.
//
// ask() reads POST api/ask/stream (server-sent events: step, delta, replace,
// done, error) with fetch, as EventSource can't POST. It falls back to POST
// api/ask only when the server answers that it has no stream (404 or 405, or a
// reply that is neither a stream nor JSON). A stream that breaks, or a request
// that fails on the way, is an error: the server may already be answering it,
// and asking again would spend a second answer of the free model's daily quota.
// Before onError, onStep gets {id: "error", status: "error", label: message},
// so the steps block can stop showing "Working…".
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var UNREACHABLE = "Couldn't reach the server. Check your connection and try again.";
  var CUT_OFF = "The answer was cut off before it finished. Please ask again.";

  function divisions() {
    return fetch("api/divisions").then(function (r) { return r.json(); });
  }

  function warm() {
    return fetch("api/warm", { method: "POST" });
  }

  function post(path, request) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    });
  }

  // Server-sent events from text that arrives in arbitrary chunks: an event, a
  // line or a CRLF pair can be split across two chunks. onEvent(name, data).
  function sseParser(onEvent) {
    var pending = "", name = "", data = [];
    function line(text) {
      if (text === "") {
        if (data.length) onEvent(name || "message", data.join("\n"));
        name = ""; data = [];
        return;
      }
      if (text.charAt(0) === ":") return; // a comment
      var colon = text.indexOf(":");
      var field = colon < 0 ? text : text.slice(0, colon);
      var value = colon < 0 ? "" : text.slice(colon + 1);
      if (value.charAt(0) === " ") value = value.slice(1);
      if (field === "event") name = value;
      else if (field === "data") data.push(value);
    }
    return {
      push: function (chunk) {
        pending += chunk;
        var start = 0;
        for (var i = 0; i < pending.length; i++) {
          var c = pending.charAt(i);
          if (c !== "\n" && c !== "\r") continue;
          if (c === "\r" && i + 1 === pending.length) break; // its "\n" may be in the next chunk
          line(pending.slice(start, i));
          if (c === "\r" && pending.charAt(i + 1) === "\n") i++;
          start = i + 1;
        }
        pending = pending.slice(start);
      },
      end: function () { if (pending) line(pending); line(""); pending = ""; }
    };
  }

  function unexpected(status) { return "The server returned an unexpected response (" + status + ")."; }
  function jsonOrNull(res) { return res.json().catch(function () { return null; }); }

  // The answer from POST api/ask: the fallback when the stream can't be read.
  function askOnce(request, done, fail) {
    return post("api/ask", request).then(function (res) {
      return jsonOrNull(res).then(function (data) {
        if (data && data.error) fail(data.error);
        // A 422 from request validation is JSON too ({detail}), but not an answer.
        else if (!res.ok || !data) fail(unexpected(res.status));
        else done(data);
      });
    }, function () {
      fail(UNREACHABLE);
    });
  }

  function ask(request, handlers) {
    var settled = false, events = 0;
    function done(payload) {
      if (settled) return;
      settled = true;
      handlers.onDone(payload);
    }
    function fail(message) {
      if (settled) return;
      settled = true;
      // The chat must hear the error even if the steps block throws on its error step.
      try { handlers.onStep({ id: "error", status: "error", label: message }); } finally { handlers.onError(message); }
    }
    function onEvent(name, text) {
      if (settled) return;
      var data;
      try { data = JSON.parse(text); } catch (e) { return; }
      events++;
      if (name === "step") handlers.onStep(data);
      else if (name === "delta") handlers.onDelta(data.text);
      else if (name === "replace") handlers.onReplace(data.text);
      else if (name === "done") done(data);
      else if (name === "error") fail(data.error);
    }
    function fallback() { return askOnce(request, done, fail); }
    // Once the stream request may have reached the server it is never sent again to api/ask:
    // the server could already be answering it, and a second copy would spend another model
    // call and rate-limit slot. The visitor gets an error and the chat's Try again instead.
    function broken() {
      if (settled) return;
      return fail(events ? CUT_OFF : UNREACHABLE);
    }

    return post("api/ask/stream", request).then(function (res) {
      var type = res.headers.get("Content-Type") || "";
      if (type.indexOf("text/event-stream") < 0) {
        return jsonOrNull(res).then(function (data) {
          // The checks (a bad question, the rate limit) answer with JSON, as api/ask does: no fallback.
          if (data && data.error) return fail(data.error);
          // No stream here (an older server: 404 or 405, or a page that isn't JSON): ask api/ask instead.
          if (!data || res.ok || res.status === 404 || res.status === 405) return fallback();
          fail(unexpected(res.status)); // e.g. 422: api/ask would refuse the same request
        });
      }
      var parser = sseParser(onEvent);
      if (!res.body || !res.body.getReader) {
        // No readable stream in this browser: the events all arrive at the end, still from this one request.
        return res.text().then(function (text) { parser.push(text); parser.end(); return broken(); }, broken);
      }
      var reader = res.body.getReader(), decoder = new TextDecoder();
      function stop() { reader.cancel().catch(function () {}); }
      function read() {
        return reader.read().then(function (part) {
          if (part.done) {
            parser.push(decoder.decode());
            parser.end();
            return broken(); // nothing if done or error arrived
          }
          // stream: true keeps a multi-byte character split across chunks (the "…" in a label) whole.
          parser.push(decoder.decode(part.value, { stream: true }));
          if (settled) return stop();
          return read();
        });
      }
      return read().catch(function () { stop(); return broken(); });
    }, function () { fail(UNREACHABLE); }).catch(function (e) {
      // Only a handler that threw gets here; the chat still has to hear the end of the answer.
      if (window.console) console.error(e);
      fail(UNREACHABLE);
    });
  }

  App.api = { divisions: divisions, warm: warm, ask: ask };
})();
