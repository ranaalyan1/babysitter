/**
 * Tool-call schema validation + coercion, modeled on
 * [Instructor](https://github.com/567-labs/instructor)'s "validate,
 * then turn the failure into an error-informed retry prompt" loop: a
 * generic re-ask ("try again") recovers a model maybe half the time,
 * but a re-ask that quotes the *exact* field and *exact* problem
 * ("`limit` must be a number, you sent the string \"ten\"") resolves
 * the overwhelming majority of failures in one extra turn, because it
 * gives the model something concrete to fix rather than asking it to
 * guess what it did wrong.
 *
 * This module is intentionally a light JSON-Schema-subset validator
 * (object/array/string/number/boolean/enum/required, the shape
 * test0's `ToolParameterSchema` already uses) rather than pulling in a
 * full Ajv/Zod dependency: repairgate's whole value proposition is
 * being a thin, fast, always-on layer in front of every tool call, and
 * the schemas tool authors actually publish (MCP tool `inputSchema`,
 * OpenAI/Anthropic tool specs) are simple enough that a hand-rolled
 * subset validator covers the real-world cases weak models get wrong:
 * wrong primitive type, missing required field, single value where an
 * array was expected, and stringly-typed numbers/booleans.
 */

export interface JsonSchemaLike {
  type?: "object" | "array" | "string" | "number" | "integer" | "boolean" | "null";
  properties?: Record<string, JsonSchemaLike>;
  required?: string[];
  items?: JsonSchemaLike;
  enum?: unknown[];
  additionalProperties?: boolean;
}

export interface ValidationIssue {
  /** Dotted path to the offending field, e.g. "args.limit" or "args.tags[0]". */
  path: string;
  message: string;
  expected?: string;
  received?: string;
}

export interface ValidateResult {
  ok: boolean;
  /** Value with cheap, unambiguous coercions applied (e.g. "42" -> 42) even when still invalid overall. */
  value: unknown;
  issues: ValidationIssue[];
  /** True if any coercion (type-widening, not a structural fix) was applied. */
  coerced: boolean;
}

function describeType(v: unknown): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v;
}

function coercePrimitive(value: unknown, schema: JsonSchemaLike): { value: unknown; coerced: boolean } {
  const type = schema.type;
  if (type === "number" || type === "integer") {
    if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
      return { value: Number(value), coerced: true };
    }
  }
  if (type === "boolean") {
    if (value === "true") return { value: true, coerced: true };
    if (value === "false") return { value: false, coerced: true };
  }
  if (type === "string") {
    if (typeof value === "number" || typeof value === "boolean") {
      return { value: String(value), coerced: true };
    }
  }
  if (type === "array" && value !== undefined && !Array.isArray(value)) {
    // A weak model very commonly emits a bare scalar where a one-element array was expected.
    return { value: [value], coerced: true };
  }
  return { value, coerced: false };
}

function validateNode(value: unknown, schema: JsonSchemaLike, path: string, issues: ValidationIssue[]): { value: unknown; coerced: boolean } {
  let coercedAny = false;

  if (schema.enum && value !== undefined && !schema.enum.includes(value)) {
    issues.push({ path, message: `must be one of ${JSON.stringify(schema.enum)}`, expected: schema.enum.join(" | "), received: JSON.stringify(value) });
    return { value, coerced: false };
  }

  const { value: coercedValue, coerced } = coercePrimitive(value, schema);
  if (coerced) {
    value = coercedValue;
    coercedAny = true;
  }

  switch (schema.type) {
    case "object": {
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        issues.push({ path, message: "must be an object", expected: "object", received: describeType(value) });
        return { value, coerced: coercedAny };
      }
      const obj = value as Record<string, unknown>;
      for (const key of schema.required ?? []) {
        if (!(key in obj) || obj[key] === undefined) {
          issues.push({ path: `${path}.${key}`, message: `missing required field "${key}"`, expected: schema.properties?.[key]?.type ?? "any" });
        }
      }
      if (schema.properties) {
        for (const [key, propSchema] of Object.entries(schema.properties)) {
          if (obj[key] === undefined) continue;
          const result = validateNode(obj[key], propSchema, `${path}.${key}`, issues);
          obj[key] = result.value;
          coercedAny = coercedAny || result.coerced;
        }
      }
      return { value: obj, coerced: coercedAny };
    }
    case "array": {
      if (!Array.isArray(value)) {
        issues.push({ path, message: "must be an array", expected: "array", received: describeType(value) });
        return { value, coerced: coercedAny };
      }
      if (schema.items) {
        value = value.map((item, i) => {
          const result = validateNode(item, schema.items as JsonSchemaLike, `${path}[${i}]`, issues);
          coercedAny = coercedAny || result.coerced;
          return result.value;
        });
      }
      return { value, coerced: coercedAny };
    }
    case "string":
      if (typeof value !== "string") {
        issues.push({ path, message: "must be a string", expected: "string", received: describeType(value) });
      }
      return { value, coerced: coercedAny };
    case "number":
    case "integer":
      if (typeof value !== "number" || Number.isNaN(value)) {
        issues.push({ path, message: "must be a number", expected: "number", received: describeType(value) });
      } else if (schema.type === "integer" && !Number.isInteger(value)) {
        issues.push({ path, message: "must be an integer", expected: "integer", received: String(value) });
      }
      return { value, coerced: coercedAny };
    case "boolean":
      if (typeof value !== "boolean") {
        issues.push({ path, message: "must be a boolean", expected: "boolean", received: describeType(value) });
      }
      return { value, coerced: coercedAny };
    default:
      return { value, coerced: coercedAny };
  }
}

export function validateAgainstSchema(value: unknown, schema: JsonSchemaLike): ValidateResult {
  const issues: ValidationIssue[] = [];
  const result = validateNode(value, schema, "args", issues);
  return { ok: issues.length === 0, value: result.value, issues, coerced: result.coerced };
}

/**
 * Render validation issues as a short, model-facing correction message —
 * Instructor's "error-informed retry" nudge, scoped to tool-call args.
 */
export function issuesToNudge(toolName: string, issues: ValidationIssue[]): string {
  const lines = issues.map((i) => `- ${i.path}: ${i.message}${i.received ? ` (got ${i.received})` : ""}`);
  return (
    `Your call to tool "${toolName}" had invalid arguments:\n${lines.join("\n")}\n\n` +
    `Call "${toolName}" again with corrected arguments that satisfy its schema. ` +
    `Respond with only the corrected tool call, no explanation.`
  );
}
