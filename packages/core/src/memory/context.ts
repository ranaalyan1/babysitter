import type { MemoryRecord, ModelMessage, SkillDescriptor } from "../types/index.js";
import { MemoryStore } from "./store.js";

export interface ContextInputs {
  task: string;
  conversation?: ModelMessage[];
  projectScope?: string;
  skills?: SkillDescriptor[];
  toolResults?: Array<{ tool: string; output: unknown }>;
  previousAgentResults?: Array<{ agentId: string; summary: string }>;
  /** Roughly how many characters of context we're willing to send. */
  budgetChars?: number;
}

export interface AssembledContext {
  messages: ModelMessage[];
  memoryUsed: MemoryRecord[];
  approxChars: number;
}

/**
 * Context Management (section 11).
 *
 * Combines current task + relevant conversation + project memory + skills
 * + tool results + previous agent results into a single message list,
 * trimming/summarizing to stay under budget rather than dumping everything.
 */
export class ContextManager {
  constructor(private readonly memory: MemoryStore) {}

  async assemble(inputs: ContextInputs): Promise<AssembledContext> {
    const budget = inputs.budgetChars ?? 12_000;
    const messages: ModelMessage[] = [];
    let used = 0;

    const push = (msg: ModelMessage): boolean => {
      if (used + msg.content.length > budget) return false;
      messages.push(msg);
      used += msg.content.length;
      return true;
    };

    // 1. Relevant project memory (retrieved, not dumped in full).
    let memoryUsed: MemoryRecord[] = [];
    if (inputs.projectScope) {
      memoryUsed = await this.memory.recall({ scope: inputs.projectScope, text: inputs.task, limit: 8 });
      if (memoryUsed.length) {
        push({
          role: "system",
          content:
            "Relevant project memory:\n" +
            memoryUsed.map((m) => `- [${m.type}/${m.key}] ${summarize(m.value)}`).join("\n"),
        });
      }
    }

    // 2. Skills (instructions only, trimmed).
    if (inputs.skills?.length) {
      push({
        role: "system",
        content:
          "Active skills:\n" +
          inputs.skills.map((s) => `## ${s.metadata.name}\n${truncate(s.instructions, 1200)}`).join("\n\n"),
      });
    }

    // 3. Previous agent results.
    if (inputs.previousAgentResults?.length) {
      push({
        role: "system",
        content:
          "Results from other agents so far:\n" +
          inputs.previousAgentResults.map((r) => `- ${r.agentId}: ${r.summary}`).join("\n"),
      });
    }

    // 4. Tool results.
    if (inputs.toolResults?.length) {
      push({
        role: "system",
        content:
          "Recent tool results:\n" +
          inputs.toolResults.map((t) => `- ${t.tool}: ${truncate(JSON.stringify(t.output), 400)}`).join("\n"),
      });
    }

    // 5. Relevant conversation history (most recent first, trimmed to budget).
    if (inputs.conversation?.length) {
      const recent = [...inputs.conversation].slice(-10);
      for (const m of recent) {
        if (!push(m)) break;
      }
    }

    // 6. The current task itself always gets included, even if it means
    // trimming something above in a stricter implementation.
    messages.push({ role: "user", content: inputs.task });

    return { messages, memoryUsed, approxChars: used + inputs.task.length };
  }
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

function summarize(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return truncate(text, 300);
}
