// Server-sent events from text that arrives in arbitrary chunks: an event, a line or a
// CRLF pair can be split across two chunks (ported from public/js/api.js). EventSource
// can't POST, so the stream is read with fetch and parsed here.
export type SseParser = {
  push(chunk: string): void;
  /** The stream is over: the last line and event, if any, are dispatched. */
  end(): void;
};

export function sseParser(onEvent: (name: string, data: string) => void): SseParser {
  let pending = "";
  let name = "";
  let data: string[] = [];

  function line(text: string) {
    if (text === "") {
      if (data.length) onEvent(name || "message", data.join("\n"));
      name = "";
      data = [];
      return;
    }
    if (text.startsWith(":")) return; // a comment
    const colon = text.indexOf(":");
    const field = colon < 0 ? text : text.slice(0, colon);
    let value = colon < 0 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }

  return {
    push(chunk) {
      pending += chunk;
      let start = 0;
      for (let i = 0; i < pending.length; i++) {
        const c = pending[i];
        if (c !== "\n" && c !== "\r") continue;
        if (c === "\r" && i + 1 === pending.length) break; // its "\n" may be in the next chunk
        line(pending.slice(start, i));
        if (c === "\r" && pending[i + 1] === "\n") i++;
        start = i + 1;
      }
      pending = pending.slice(start);
    },
    end() {
      if (pending) line(pending);
      line("");
      pending = "";
    },
  };
}
