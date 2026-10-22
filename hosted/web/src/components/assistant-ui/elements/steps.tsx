import "./steps.css";

import { type DataMessagePartComponent, useAuiState } from "@assistant-ui/react";
import { useId, useState } from "react";
import type { AnswerMetadata, StepEvent } from "@/types";
import { modelName, seconds } from "./format";

type BlockState = "running" | "done" | "error" | "stopped";

const TITLES: Record<BlockState, string> = {
  running: "Working…",
  done: "Done",
  error: "Couldn't finish",
  stopped: "Stopped",
};

/**
 * The `steps` data part: "Working…" while the answer is on its way, then "Done in N s"
 * with the model, over the steps on a dotted timeline (the old page's steps.js). It
 * collapses once the answer is done, unless the visitor opened or closed it first.
 */
export const StepsPart: DataMessagePartComponent<StepEvent[]> = ({ data }) => {
  const listId = useId();
  const status = useAuiState((s) => s.message.status);
  const payload = useAuiState((s) => (s.message.metadata.custom as AnswerMetadata).payload);
  const [chosen, setChosen] = useState<boolean | null>(null);

  const state: BlockState =
    status?.type === "running" || status?.type === "requires-action"
      ? "running"
      : status?.type === "incomplete"
        ? status.reason === "cancelled"
          ? "stopped"
          : "error"
        : "done";
  const open = chosen ?? state !== "done";
  const total = payload?.timing_ms?.total;
  const title = state === "done" && typeof total === "number" ? `Done in ${seconds(total)}` : TITLES[state];

  let model = "";
  let modelTip = "";
  if (state === "done" && payload?.model) {
    model = modelName(payload.model);
    modelTip = payload.model;
    if (payload.retried && payload.first_model) {
      model += `, retried after ${modelName(payload.first_model)}`;
      modelTip += ` (retried after ${payload.first_model})`;
    }
  }

  const steps = Array.isArray(data) ? data : [];
  return (
    <div className="steps-block mb-2.5" data-state={state}>
      <button
        type="button"
        className="steps-head"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setChosen(!open)}
      >
        <span className="steps-icon" aria-hidden="true" />
        <span className="steps-title">{title}</span>
        <span className="steps-chevron" aria-hidden="true" />
        {model && (
          <span className="steps-meta" title={modelTip}>
            {model}
          </span>
        )}
      </button>
      <ol className="steps-list" id={listId} hidden={!open}>
        {steps.map((step) => {
          const shown = step.status !== "done" && state !== "running" ? "failed" : step.status === "done" ? "done" : "running";
          return (
            <li key={step.id} className="step" data-step={step.id} data-status={shown}>
              <span className="step-label">{step.label ?? step.id}</span>
              <span className="step-ms">{shown === "done" ? seconds(step.ms ?? 0) : ""}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
