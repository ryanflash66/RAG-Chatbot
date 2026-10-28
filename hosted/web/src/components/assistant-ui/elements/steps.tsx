import "./steps.css";

import { type DataMessagePartComponent, useAuiState } from "@assistant-ui/react";
import { CheckIcon, CircleDashedIcon, CircleXIcon, LoaderCircleIcon } from "lucide-react";
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

// Read before each label, as the icons alone say nothing to a screen reader (as public/js/steps.js).
const STATUS_TEXT = { pending: "Not started: ", running: "In progress: ", done: "Done: ", failed: "Stopped: " };

type StepStatus = keyof typeof STATUS_TEXT;

// The icons of a task list (asked for on Oct 28, after the first React steps used CSS
// circles): a dashed circle not started, a spinner in progress, a filled check done.
function StepIcon({ status }: { status: StepStatus }) {
  if (status === "done") {
    return (
      <span className="step-icon step-icon-done" aria-hidden="true">
        <CheckIcon strokeWidth={3.5} />
      </span>
    );
  }
  const Icon = status === "running" ? LoaderCircleIcon : status === "failed" ? CircleXIcon : CircleDashedIcon;
  return <Icon className="step-icon" aria-hidden="true" />;
}

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
    // Same rule as public/js/steps.js: "after" only when another model gave the final reply.
    if (payload.retried && payload.first_model && payload.first_model !== payload.model) {
      model += `, retried after ${modelName(payload.first_model)}`;
      modelTip += ` (retried after ${payload.first_model})`;
    } else if (payload.retried) {
      model += ", retried";
      modelTip += " (retried)";
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
          // A pending step hasn't started, so it is never shown running or failed.
          const shown: StepStatus =
            step.status === "done"
              ? "done"
              : step.status === "pending"
                ? "pending"
                : state !== "running"
                  ? "failed"
                  : "running";
          return (
            <li key={step.id} className="step" data-step={step.id} data-status={shown}>
              <StepIcon status={shown} />
              <span className="sr-only">{STATUS_TEXT[shown]}</span>
              <span className="step-label">{step.label ?? step.id}</span>
              <span className="step-ms">{shown === "done" ? seconds(step.ms ?? 0) : ""}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
