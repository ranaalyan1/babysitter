import { createServer, type Server } from "node:http";
import { RepairgateGateway } from "../gateway.js";
import { fromOpenAIChat, toOpenAIChat, type OpenAIChatRequest } from "../dialect/normalize.js";
import type { RawToolCall } from "../types.js";

/**
 * The daemon: "A local server you point Cursor / Claude Code / Codex
 * at." Exposes a single OpenAI-Chat-Completions-compatible endpoint
 * (`POST /v1/chat/completions`) — the format every one of the named
 * tools already knows how to hit via a custom "base URL" setting — so
 * plugging repairgate in is a base-URL change, not an integration
 * project. Anthropic/Responses-shaped requests are exactly what
 * `dialect/normalize.ts` exists to translate; wiring those two
 * additional listen paths is server plumbing (job "3. thin gateway
 * shell", not the differentiator) left as a documented follow-up in
 * ARCHITECTURE.md rather than duplicated three times here.
 *
 * The session id is read from an OpenAI-non-standard-but-widely-
 * supported `x-repairgate-session` header (or the request body's
 * `user` field as a fallback), because the whole product only works if
 * the calling tool's session survives across the "25 calls in a row"
 * the spec describes — see gateway.ts and session/session.ts for where
 * that statefulness actually lives.
 */
export interface DaemonOptions {
  port: number;
  host?: string;
}

export function createDaemon(gateway: RepairgateGateway, options: DaemonOptions): Server {
  const server = createServer((req, res) => {
    if (req.method !== "POST" || !req.url?.startsWith("/v1/chat/completions")) {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "not found. POST /v1/chat/completions" }));
      return;
    }

    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", async () => {
      try {
        const parsed = JSON.parse(body) as OpenAIChatRequest & { user?: string };
        const sessionId = (req.headers["x-repairgate-session"] as string | undefined) ?? parsed.user ?? "default";

        const turnRequest = fromOpenAIChat(parsed);
        const result = await gateway.handleStep({ ...turnRequest, sessionId });

        if (!result.success) {
          res.writeHead(502, { "content-type": "application/json" });
          res.end(JSON.stringify({ error: { message: result.reason ?? "repairgate: step failed", type: "repairgate_step_failed", quotaBlocked: result.quotaBlocked ?? false } }));
          return;
        }

        const rawCalls: RawToolCall[] = result.calls.map((c) => ({ id: c.id, name: c.name, argsText: JSON.stringify(c.args) }));
        const message = toOpenAIChat({ content: "", toolCalls: rawCalls, finishReason: rawCalls.length > 0 ? "tool_calls" : "stop" });

        res.writeHead(200, { "content-type": "application/json" });
        res.end(
          JSON.stringify({
            id: `repairgate-${Date.now()}`,
            object: "chat.completion",
            model: result.modelId,
            choices: [{ index: 0, message, finish_reason: rawCalls.length > 0 ? "tool_calls" : "stop" }],
            repairgate: { escalated: result.escalated, attempts: result.attempts, sessionId },
          })
        );
      } catch (err) {
        res.writeHead(400, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: { message: err instanceof Error ? err.message : String(err) } }));
      }
    });
  });

  server.listen(options.port, options.host ?? "0.0.0.0");
  return server;
}
