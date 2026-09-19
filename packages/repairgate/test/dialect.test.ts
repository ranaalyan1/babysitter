import { describe, expect, it } from "vitest";
import {
  fromAnthropicMessages,
  fromOpenAIChat,
  fromOpenAIResponses,
  toAnthropicMessages,
  toOpenAIChat,
  toOpenAIResponses,
} from "../src/dialect/normalize.js";

describe("OpenAI Chat Completions dialect", () => {
  it("normalizes messages + tools into ModelTurnRequest", () => {
    const req = fromOpenAIChat({
      messages: [
        { role: "system", content: "You are a coding agent." },
        { role: "user", content: "Read config.json" },
      ],
      tools: [{ type: "function", function: { name: "read_file", description: "read", parameters: { type: "object", properties: {} } } }],
    });
    expect(req.messages).toHaveLength(2);
    expect(req.tools[0].name).toBe("read_file");
    expect(req.expectToolCall).toBe(true);
  });

  it("round-trips a tool-call response back into OpenAI shape", () => {
    const message = toOpenAIChat({ content: "", toolCalls: [{ id: "c1", name: "read_file", argsText: '{"path":"a"}' }], finishReason: "tool_calls" });
    expect(message.content).toBeNull();
    expect(message.tool_calls?.[0].function.name).toBe("read_file");
  });

  it("emits a plain text assistant message when there are no tool calls", () => {
    const message = toOpenAIChat({ content: "Done.", toolCalls: [], finishReason: "stop" });
    expect(message.content).toBe("Done.");
    expect(message.tool_calls).toBeUndefined();
  });
});

describe("Anthropic Messages dialect", () => {
  it("hoists system into a system-role message and flattens tool_result blocks", () => {
    const req = fromAnthropicMessages({
      system: "You are a coding agent.",
      messages: [
        { role: "user", content: "Read config.json" },
        { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "file contents" }] },
      ],
      tools: [{ name: "read_file", input_schema: { type: "object", properties: {} } }],
    });
    expect(req.messages[0]).toEqual({ role: "system", content: "You are a coding agent." });
    expect(req.messages.some((m) => m.role === "tool" && m.toolCallId === "t1")).toBe(true);
  });

  it("renders a tool-call response as a tool_use content block", () => {
    const message = toAnthropicMessages({ content: "", toolCalls: [{ id: "t1", name: "read_file", argsText: '{"path":"a"}' }], finishReason: "tool_calls" });
    const block = message.content.find((b) => b.type === "tool_use");
    expect(block).toBeDefined();
    if (block?.type === "tool_use") {
      expect(block.name).toBe("read_file");
      expect(block.input).toEqual({ path: "a" });
    }
  });
});

describe("OpenAI Responses dialect", () => {
  it("normalizes input items into ModelTurnRequest", () => {
    const req = fromOpenAIResponses({
      input: [
        { type: "message", role: "user", content: "Read config.json" },
        { type: "function_call_output", call_id: "c1", output: "contents" },
      ],
      tools: [{ type: "function", name: "read_file", parameters: { type: "object", properties: {} } }],
    });
    expect(req.messages.some((m) => m.role === "tool" && m.toolCallId === "c1")).toBe(true);
    expect(req.tools[0].name).toBe("read_file");
  });

  it("renders a tool-call response as a function_call item", () => {
    const items = toOpenAIResponses({ content: "", toolCalls: [{ id: "c1", name: "read_file", argsText: '{"path":"a"}' }], finishReason: "tool_calls" });
    expect(items.some((i) => i.type === "function_call")).toBe(true);
  });
});
