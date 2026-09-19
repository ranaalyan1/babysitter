/**
 * repairgate — "A stateful repair-and-escalation daemon that sits
 * between a coding tool and free LLMs, and makes weak models produce
 * competent agentic output."
 *
 * See docs/ARCHITECTURE.md in this package for the design rationale
 * and the five jobs this implements: session state, tool-call repair,
 * silent escalation, task-level quota orchestration, and dialect
 * normalization.
 */

export { healJson, type JsonHealResult } from "./repair/json-heal.js";
export { validateAgainstSchema, issuesToNudge, type JsonSchemaLike, type ValidateResult, type ValidationIssue } from "./repair/schema-validate.js";
export { RepairEngine, type RepairAttemptResult, type RepairEngineOptions } from "./repair/engine.js";

export { Session, SessionStore, type StepState, type SessionUsage } from "./session/session.js";

export { EscalationController, type EscalationLadder, type EscalationStepResult } from "./escalation/controller.js";

export { QuotaOrchestrator, type TaskQuota, type ReserveResult } from "./quota/orchestrator.js";

export {
  fromOpenAIChat,
  toOpenAIChat,
  fromAnthropicMessages,
  toAnthropicMessages,
  fromOpenAIResponses,
  toOpenAIResponses,
  rawCallsFromOpenAIToolCalls,
  type Dialect,
  type OpenAIChatRequest,
  type AnthropicMessagesRequest,
  type OpenAIResponsesRequest,
} from "./dialect/normalize.js";

export { DumbModel, ReliableModel, type DumbFailureMode, type DumbModelOptions } from "./providers/dumb-model.js";
export { HttpModelBackend, type HttpModelBackendOptions } from "./providers/http-backend.js";

export { RepairgateGateway, type GatewayOptions, type HandleStepRequest, type HandleStepResult } from "./gateway.js";

export { createDaemon, type DaemonOptions } from "./server/daemon.js";

export type { ModelBackend, ModelTurnRequest, ModelTurnResponse, RawToolCall, RepairOutcome, RepairedToolCall, ToolSpec } from "./types.js";
