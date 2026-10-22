import type { ChatModelAdapter } from "@assistant-ui/react";
import { selectedDocuments, useApp } from "@/state";
import { messageText, turnsFor } from "./history";
import { applyEvent, NOTHING_YET, toResult } from "./parts";
import { ask } from "./stream";

// The thread's answers, from POST api/ask/stream (see stream.ts). It runs under
// useLocalRuntime: assistant-ui keeps the thread and calls run() once per question, with
// the thread so far ending in the question, and shows what each yield returns.
export const answerAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const app = useApp.getState();
    const { asker, target } = app;
    if (!asker || !target) throw new Error("The demo hasn't finished loading. Please refresh the page.");
    // The sources panel follows the newest answer again, whichever one it was showing.
    app.showAnswer(null);
    const request = {
      question: messageText(messages[messages.length - 1]),
      asker,
      target,
      history: turnsFor(messages, target),
      documents: selectedDocuments(app, target),
    };
    let answer = NOTHING_YET;
    yield toResult(answer, target); // "Working…" from the start, before the first step arrives
    for await (const event of ask(request, abortSignal)) {
      answer = applyEvent(answer, event);
      yield toResult(answer, target);
    }
  },
};
