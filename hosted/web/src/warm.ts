import { apiPath } from "@/api";
import { useApp } from "@/state";

// Loads the search models while the visitor picks divisions and types (public/js/app.js's
// App.warmUp). api/warm answers once they are loaded, at once on a warm instance; it is
// re-sent at most every 30 s because an idle instance can be stopped.
const COOLDOWN_MS = 30_000;
let inFlight = false;
let lastAt = 0;

export function warmUp(): void {
  if (inFlight || Date.now() - lastAt < COOLDOWN_MS) return;
  inFlight = true;
  // The cooldown follows failed attempts too, so a broken warm-up isn't retried on every keystroke.
  fetch(apiPath("warm"), { method: "POST" })
    .catch(() => undefined)
    .then(() => {
      inFlight = false;
      lastAt = Date.now();
    });
}

// Once the divisions arrive. A store subscription rather than an effect in DocsPanel,
// which on phones only mounts when its drawer opens.
useApp.subscribe((state, prev) => {
  if (state.divisions !== prev.divisions && state.divisions.length) warmUp();
});
