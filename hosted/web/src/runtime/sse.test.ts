// @vitest-environment node
import { describe, expect, it } from "vitest";
import { sseParser } from "./sse";

function parse(chunks: string[], end = true): [string, string][] {
  const events: [string, string][] = [];
  const parser = sseParser((name, data) => events.push([name, data]));
  for (const chunk of chunks) parser.push(chunk);
  if (end) parser.end();
  return events;
}

const STREAM =
  'event: step\ndata: {"id":"read","status":"start","label":"Reading the question…"}\n\n' +
  'event: delta\ndata: {"text":"Flaggers "}\n\n' +
  ': a comment\n' +
  'event: done\ndata: {"answer":"Flaggers [1]."}\n\n';

const EXPECTED: [string, string][] = [
  ["step", '{"id":"read","status":"start","label":"Reading the question…"}'],
  ["delta", '{"text":"Flaggers "}'],
  ["done", '{"answer":"Flaggers [1]."}'],
];

describe("sseParser", () => {
  it("reads named events and skips comments", () => {
    expect(parse([STREAM])).toEqual(EXPECTED);
  });

  it("gives the same events however the text is split into chunks", () => {
    for (let at = 1; at < STREAM.length; at++) {
      expect(parse([STREAM.slice(0, at), STREAM.slice(at)])).toEqual(EXPECTED);
    }
    expect(parse(STREAM.split(""))).toEqual(EXPECTED);
  });

  it("handles CRLF and CR line ends, including a CRLF split across chunks", () => {
    const crlf = STREAM.replace(/\n/g, "\r\n");
    for (let at = 1; at < crlf.length; at++) {
      expect(parse([crlf.slice(0, at), crlf.slice(at)])).toEqual(EXPECTED);
    }
    expect(parse([STREAM.replace(/\n/g, "\r")])).toEqual(EXPECTED);
  });

  it("joins multi-line data and names an unnamed event 'message'", () => {
    expect(parse(["data: one\ndata: two\n\n"])).toEqual([["message", "one\ntwo"]]);
  });

  it("dispatches an event without its blank line only at the end", () => {
    expect(parse(['event: done\ndata: {"a":1}'], false)).toEqual([]);
    expect(parse(['event: done\ndata: {"a":1}'])).toEqual([["done", '{"a":1}']]);
  });
});
