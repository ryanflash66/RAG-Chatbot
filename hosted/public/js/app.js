// Starts the page: loads the divisions, fills the pickers, warms the models up
// and opens or closes the side drawers on phones. Runs last, after every panel's script.
(function () {
  "use strict";
  var App = window.App = window.App || {};
  var el = function (id) { return document.getElementById(id); };
  var asker = el("asker"), target = el("target");

  App.state = { divisions: [], byId: {}, maxChars: 500 };
  App.selection = function () { return { asker: asker.value, target: target.value }; };

  // Load the search models while the visitor picks divisions and types. api/warm answers once they are
  // loaded (at once on a warm instance); it is re-sent at most every 30 s because an idle instance can be stopped.
  var warm = { inFlight: false, at: 0 };
  App.warmUp = function () {
    if (warm.inFlight || Date.now() - warm.at < 30000) return;
    warm.inFlight = true;
    // The cooldown follows failed attempts too, so a broken warm-up isn't retried on every keystroke.
    App.api.warm().catch(function () {}).then(function () {
      warm.inFlight = false;
      warm.at = Date.now();
    });
  };

  function other(id) {
    var o = App.state.divisions.filter(function (d) { return d.id !== id; });
    return o.length ? o[0].id : id;
  }

  function targetChanged() {
    App.chat.showExamples(App.state.byId[target.value]);
    App.docs.setTarget(target.value);
  }

  App.setTarget = function (id) { target.value = id; targetChanged(); };

  // Drawers: below 900 px the documents and sources panels slide in over the chat.
  var scrim = el("scrim");
  App.drawers = {
    open: function (panelId) {
      App.drawers.close();
      el(panelId).classList.add("open");
      el(panelId === "docs-panel" ? "open-docs" : "open-sources").setAttribute("aria-expanded", "true");
      scrim.hidden = false;
    },
    close: function () {
      ["docs-panel", "sources-panel"].forEach(function (id) { el(id).classList.remove("open"); });
      ["open-docs", "open-sources"].forEach(function (id) { el(id).setAttribute("aria-expanded", "false"); });
      scrim.hidden = true;
    }
  };
  el("open-docs").addEventListener("click", function () { App.drawers.open("docs-panel"); });
  el("open-sources").addEventListener("click", function () { App.drawers.open("sources-panel"); });
  scrim.addEventListener("click", App.drawers.close);
  Array.prototype.forEach.call(document.querySelectorAll("[data-close-drawer]"), function (b) {
    b.addEventListener("click", App.drawers.close);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") App.drawers.close(); });

  asker.addEventListener("change", function () {
    if (asker.value === target.value) App.setTarget(other(asker.value));
    App.warmUp();
  });
  target.addEventListener("change", function () { targetChanged(); App.warmUp(); });

  function option(d) {
    var o = document.createElement("option");
    o.value = d.id; o.textContent = d.name;
    return o;
  }

  App.sources.init();
  App.api.divisions().then(function (data) {
    App.state.divisions = data.divisions;
    App.state.maxChars = data.max_question_chars || 500;
    data.divisions.forEach(function (d) {
      App.state.byId[d.id] = d;
      asker.appendChild(option(d));
      target.appendChild(option(d));
    });
    App.docs.render(data.divisions);
    App.chat.init();
    asker.value = data.divisions[0].id;
    App.setTarget(other(asker.value));
    App.warmUp();
  }).catch(function () {
    App.chat.fail("Couldn't load the demo. Please refresh the page.");
  });
})();
