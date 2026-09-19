/**
 * test0 V5 — shared core types
 *
 * These types are intentionally provider-agnostic. Nothing in this file
 * should ever reference a specific vendor (OpenAI, Anthropic, Google, ...).
 */

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

export type ModelCategory =
  | "free-browser"
  | "free-api"
  | "paid-api"
  | "local"
  | "custom";

export interface ModelCapabilities {
  coding: number; // 0-1 relative capability score
  reasoning: number;
  vision: boolean;
  toolUse: boolean;
  maxContextTokens: number;
  streaming: boolean;
}

export interface ModelCostProfile {
  /** USD per 1M input tokens. 0 for free models. */
  inputPerMillion: number;
  /** USD per 1M output tokens. 0 for free models. */
  outputPerMillion: number;
  isFree: boolean;
}

export interface ModelDescriptor {
  id: string;
  provider: string;
  displayName: string;
  category: ModelCategory;
  capabilities: ModelCapabilities;
  cost: ModelCostProfile;
  /** Rough p50 latency in ms for a short completion, used by the router. */
  typicalLatencyMs: number;
  available: boolean;
}

export interface ModelMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  name?: string;
}

export interface ModelRequest {
  messages: ModelMessage[];
  taskType?: TaskType;
  maxTokens?: number;
  temperature?: number;
  requireVision?: boolean;
  requireToolUse?: boolean;
  metadata?: Record<string, unknown>;
}

export interface ModelUsage {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export interface ModelResponse {
  modelId: string;
  provider: string;
  content: string;
  usage: ModelUsage;
  latencyMs: number;
  finishReason: "stop" | "length" | "error";
  raw?: unknown;
}

export interface ModelProvider {
  id: string;
  displayName: string;
  category: ModelCategory;
  /** Returns the list of models this provider currently exposes. */
  listModels(): Promise<ModelDescriptor[]>;
  /** Whether the provider is reachable / configured right now. */
  checkAvailability(): Promise<boolean>;
  /** Execute a single completion request against a specific model id. */
  complete(modelId: string, request: ModelRequest): Promise<ModelResponse>;
}

export class ModelProviderError extends Error {
  constructor(
    message: string,
    public readonly provider: string,
    public readonly kind: "rate-limited" | "unavailable" | "auth" | "unknown" = "unknown"
  ) {
    super(message);
    this.name = "ModelProviderError";
  }
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

export type TaskType =
  | "coding"
  | "reasoning"
  | "research"
  | "vision"
  | "review"
  | "testing"
  | "planning"
  | "documentation"
  | "general";

export type RoutingPolicy = "free-first" | "quality-first" | "local-first" | "cheapest" | "fastest";

export interface RoutingRequirements {
  taskType: TaskType;
  requireVision?: boolean;
  requireToolUse?: boolean;
  minContextTokens?: number;
  maxLatencyMs?: number;
  maxCostUsd?: number;
  preferredModels?: string[];
  excludedModels?: string[];
}

export interface RoutingDecision {
  chosen: ModelDescriptor;
  candidates: ModelDescriptor[];
  attempted: Array<{ modelId: string; outcome: "success" | "rate-limited" | "unavailable" | "error" }>;
  policy: RoutingPolicy;
  reason: string;
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

export interface SkillMetadata {
  name: string;
  version: string;
  description: string;
  tags: string[];
  requiredTools?: string[];
  dependencies?: string[];
  author?: string;
}

export interface SkillDescriptor {
  metadata: SkillMetadata;
  path: string;
  instructions: string; // rendered body of SKILL.md
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export interface ToolParameterSchema {
  type: "object";
  properties: Record<string, unknown>;
  required?: string[];
}

export interface ToolDescriptor {
  name: string;
  description: string;
  source: "builtin" | "mcp";
  serverId?: string;
  inputSchema: ToolParameterSchema;
  permissionKey: string; // e.g. "filesystem.write"
}

export interface ToolCallResult {
  ok: boolean;
  output?: unknown;
  error?: string;
  durationMs: number;
}

export interface ToolExecutor {
  name: string;
  descriptor: ToolDescriptor;
  execute(args: Record<string, unknown>): Promise<ToolCallResult>;
}

// ---------------------------------------------------------------------------
// Permissions / Security
// ---------------------------------------------------------------------------

export type PermissionDecision = "allow" | "ask" | "block";

export interface PermissionRule {
  scope: string; // e.g. "filesystem.write", "github.createPR"
  decision: PermissionDecision;
}

export interface PermissionCheckResult {
  scope: string;
  decision: PermissionDecision;
  allowed: boolean;
  reason: string;
}

export interface AuditLogEntry {
  timestamp: string;
  actor: string; // agent id or "user"
  scope: string;
  decision: PermissionDecision;
  detail?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export type MemoryType =
  | "user"
  | "project"
  | "agent"
  | "task"
  | "conversation"
  | "tool-state";

export interface MemoryRecord {
  id: string;
  type: MemoryType;
  scope: string; // e.g. project name, agent id
  key: string;
  value: unknown;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

export interface MemoryQuery {
  type?: MemoryType;
  scope?: string;
  tags?: string[];
  text?: string;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

export type AgentRole = "planner" | "coder" | "researcher" | "reviewer" | "tester" | "custom";

export interface AgentDefinition {
  id: string;
  role: AgentRole;
  description: string;
  skills: string[];
  tools: string[];
  preferredTaskTypes: TaskType[];
}

export interface PlanStep {
  id: string;
  description: string;
  assignedRole: AgentRole;
  dependsOn: string[];
  taskType: TaskType;
  status: "pending" | "in-progress" | "done" | "failed" | "skipped";
}

export interface ExecutionPlan {
  goal: string;
  steps: PlanStep[];
  createdAt: string;
}

export interface StepResult {
  stepId: string;
  agentId: string;
  status: "done" | "failed";
  summary: string;
  detail?: unknown;
  modelUsed?: string;
  toolsUsed?: string[];
}

export interface OrchestrationResult {
  goal: string;
  plan: ExecutionPlan;
  stepResults: StepResult[];
  finalReport: string;
  success: boolean;
}

// ---------------------------------------------------------------------------
// Benchmarking
// ---------------------------------------------------------------------------

export interface BenchmarkCase {
  id: string;
  taskType: TaskType;
  prompt: string;
  expectedContains?: string[];
}

export interface BenchmarkResult {
  modelId: string;
  caseId: string;
  passed: boolean;
  latencyMs: number;
  costUsd: number;
  notes?: string;
}

export interface BenchmarkSummary {
  modelId: string;
  totalCases: number;
  passed: number;
  avgLatencyMs: number;
  totalCostUsd: number;
  score: number; // 0-1
}
