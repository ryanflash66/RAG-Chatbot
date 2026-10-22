import type { ChatModelAdapter } from "@assistant-ui/react";

// Stands in until the real adapter over /api/ask/stream lands (DAR-631), so the
// scaffold can render and use assistant-ui's thread without answering anything.
export const placeholderAdapter: ChatModelAdapter = {
  async run() {
    return {
      content: [
        {
          type: "text",
          text: "This new page isn't connected to the answering service yet. Ask your question on the current page for now.",
        },
      ],
    };
  },
};
