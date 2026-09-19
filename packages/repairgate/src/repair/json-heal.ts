/**
 * JSON healing for weak-model tool-call arguments.
 *
 * Modeled on the common fix-set documented by real "LLM JSON repair"
 * tools — `json-repair-js`, `@toolsycc/json-repair`, and the
 * `tryRepairJson` patch proposed against Mastra's tool-call pipeline
 * (mastra-ai/mastra#11078) — plus Vercel AI SDK's
 * `experimental_repairToolCall` hook, which established "give the
 * pipeline one more chance to fix broken tool-call JSON before failing
 * the step" as the standard shape for this problem.
 *
 * A cheap/free model reliably produces a specific, small set of
 * malformed-JSON patterns rather than arbitrary garbage: markdown code
 * fences around the object, prose before/after it ("Here's the JSON:
 * {...}"), unquoted or single-quoted keys, trailing commas, Python/JS
 * literals (`True`/`None`/`undefined`), smart quotes, and truncated
 * output missing closing brackets. `healJson` runs a fixed pipeline of
 * targeted, ordered transforms — not a generic parser rewrite — so
 * each fix is auditable and independently testable, and returns which
 * fixes were applied so the caller (and, eventually, a human debugging
 * a flaky model) can see exactly what was wrong.
 */

export interface JsonHealResult {
  ok: boolean;
  value?: unknown;
  /** Human-readable list of the transforms that were needed to parse, in order applied. */
  fixesApplied: string[];
  /** The final string that was actually handed to JSON.parse, for debugging. */
  healedText?: string;
}

const LITERAL_FIXES: Array<[RegExp, string, string]> = [
  [/\bTrue\b/g, "true", "capitalized-true"],
  [/\bFalse\b/g, "false", "capitalized-false"],
  [/\bNone\b/g, "null", "python-none"],
  [/\bundefined\b/g, "null", "js-undefined"],
  [/\bNaN\b/g, "null", "nan-literal"],
];

function extractFromFencesOrProse(text: string): { text: string; fixed: boolean } {
  // ```json ... ``` or ``` ... ``` fences.
  const fenceMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenceMatch) {
    return { text: fenceMatch[1].trim(), fixed: true };
  }

  // Prose wrapping the JSON, e.g. "Sure! Here's the JSON: {...} Let me know if..."
  const firstBrace = text.search(/[{[]/);
  if (firstBrace > 0) {
    // Find the matching close for whichever opener comes first, scanning from the end inward.
    const opener = text[firstBrace];
    const closer = opener === "{" ? "}" : "]";
    const lastClose = text.lastIndexOf(closer);
    if (lastClose > firstBrace) {
      return { text: text.slice(firstBrace, lastClose + 1), fixed: true };
    }
  }
  return { text, fixed: false };
}

function stripComments(text: string): { text: string; fixed: boolean } {
  const stripped = text.replace(/\/\/[^\n]*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
  return { text: stripped, fixed: stripped !== text };
}

function normalizeSmartQuotes(text: string): { text: string; fixed: boolean } {
  const normalized = text.replace(/[\u2018\u2019]/g, "'").replace(/[\u201C\u201D]/g, '"');
  return { text: normalized, fixed: normalized !== text };
}

function quoteUnquotedKeys(text: string): { text: string; fixed: boolean } {
  // { key: "value" }  ->  { "key": "value" }
  // also handles keys after commas/newlines.
  const fixed = text.replace(/([{,]\s*)([A-Za-z_$][A-Za-z0-9_$]*)\s*:/g, '$1"$2":');
  return { text: fixed, fixed: fixed !== text };
}

function singleToDoubleQuotes(text: string): { text: string; fixed: boolean } {
  // Only flip single-quoted strings that look like JSON string literals
  // (avoids mangling apostrophes inside already-double-quoted strings).
  const fixed = text.replace(/'((?:[^'\\]|\\.)*)'/g, (_m, inner: string) => `"${inner.replace(/"/g, '\\"')}"`);
  return { text: fixed, fixed: fixed !== text };
}

function removeTrailingCommas(text: string): { text: string; fixed: boolean } {
  const fixed = text.replace(/,(\s*[}\]])/g, "$1");
  return { text: fixed, fixed: fixed !== text };
}

function insertMissingCommas(text: string): { text: string; fixed: boolean } {
  // ["a" "b" "c"] or {"a":1 "b":2}  ->  insert a comma between adjacent values.
  const fixed = text.replace(/("|\d|true|false|null|\}|\])\s+(?="|\{|\[|-?\d|true|false|null)/g, "$1, ");
  return { text: fixed, fixed: fixed !== text };
}

function closeUnclosedBrackets(text: string): { text: string; fixed: boolean } {
  let inString = false;
  let escape = false;
  const stack: string[] = [];
  for (const ch of text) {
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === "\\") {
      escape = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === "{" || ch === "[") stack.push(ch === "{" ? "}" : "]");
    else if (ch === "}" || ch === "]") stack.pop();
  }
  const opens = stack.length;
  if (opens === 0) return { text, fixed: false };
  return { text: text + stack.reverse().join(""), fixed: true };
}

/**
 * Attempt to parse `raw` as JSON, applying an ordered pipeline of
 * targeted repairs when the naive parse fails. Cheap parse-first so a
 * well-formed response (the common case for a healthy model) pays zero
 * repair cost.
 */
export function healJson(raw: string): JsonHealResult {
  const trimmed = raw.trim();

  // Fast path: already valid.
  try {
    return { ok: true, value: JSON.parse(trimmed), fixesApplied: [], healedText: trimmed };
  } catch {
    // fall through to repair pipeline
  }

  const fixesApplied: string[] = [];
  let text = trimmed;

  const steps: Array<[string, (t: string) => { text: string; fixed: boolean }]> = [
    ["strip-fences-or-prose", extractFromFencesOrProse],
    ["strip-comments", stripComments],
    ["normalize-smart-quotes", normalizeSmartQuotes],
    ["single-to-double-quotes", singleToDoubleQuotes],
    ["quote-unquoted-keys", quoteUnquotedKeys],
    ["remove-trailing-commas", removeTrailingCommas],
    ["insert-missing-commas", insertMissingCommas],
    ["close-unclosed-brackets", closeUnclosedBrackets],
  ];

  for (const [name, step] of steps) {
    const result = step(text);
    text = result.text;
    if (result.fixed) fixesApplied.push(name);

    try {
      return { ok: true, value: JSON.parse(text), fixesApplied, healedText: text };
    } catch {
      // keep applying the remaining steps
    }
  }

  for (const [pattern, replacement, label] of LITERAL_FIXES) {
    if (pattern.test(text)) {
      text = text.replace(pattern, replacement);
      fixesApplied.push(label);
    }
  }

  try {
    return { ok: true, value: JSON.parse(text), fixesApplied, healedText: text };
  } catch {
    return { ok: false, fixesApplied, healedText: text };
  }
}
