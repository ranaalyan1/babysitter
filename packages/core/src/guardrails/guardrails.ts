/**
 * Guardrails (test0 V5, new in this pass), modeled on
 * [Guardrails AI](https://github.com/guardrails-ai/guardrails)'s
 * validator-pipeline design and [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails)'
 * input/output "rails" split:
 *
 *  - **Input rails** run on the outbound prompt before it ever reaches a
 *    model: prompt-injection / jailbreak heuristics ("ignore previous
 *    instructions", role-override attempts), the same class of check
 *    NeMo's `check_input_safety` execution rail performs.
 *  - **Output rails** run on the model's response before it's returned
 *    to the caller: PII detection + redaction (Guardrails AI's
 *    `ValidPII`/`DetectPII` validators — email, phone, SSN, credit
 *    card) and secret/credential leakage (API-key-shaped tokens),
 *    following Guardrails AI's `on_fail=OnFailAction.FIX` "redact
 *    instead of block" default so a single flagged token doesn't waste
 *    an entire (already paid-for) completion.
 *
 * Each check is a small, independent `Validator` — same shape as a
 * Guardrails AI hub validator (`name`, `check(text)`) — so adding a new
 * rule (a topical classifier, a company-specific banned-terms list) is
 * one function, not a rewrite of the pipeline. `GuardrailEngine` is
 * intentionally regex/heuristic-based rather than ML-classifier-based
 * to stay dependency-free and fully offline; swap in a real classifier
 * or moderation API behind the same `Validator` interface for
 * production-grade recall.
 */

export type GuardrailAction = "allow" | "redact" | "block";

export interface GuardrailFinding {
  validator: string;
  category: string;
  action: GuardrailAction;
  /** Number of matches found (for redaction-style validators). */
  count?: number;
  detail?: string;
}

export interface ValidatorResult {
  action: GuardrailAction;
  category: string;
  /** For "redact": the cleaned text. Absent for "allow"/"block". */
  redactedText?: string;
  count?: number;
  detail?: string;
}

export interface Validator {
  name: string;
  check(text: string): ValidatorResult | undefined;
}

export interface GuardrailReport {
  safe: boolean;
  text: string;
  findings: GuardrailFinding[];
}

// ---------------------------------------------------------------------------
// Built-in validators
// ---------------------------------------------------------------------------

const PII_PATTERNS: Record<string, RegExp> = {
  email: /\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b/gi,
  phone: /\b(?:\+?\d{1,2}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g,
  ssn: /\b\d{3}-\d{2}-\d{4}\b/g,
  creditCard: /\b(?:\d[ -]*?){13,16}\b/g,
};

/** Guardrails AI `DetectPII`-equivalent: find + redact common PII shapes in output text. */
export const piiRedactValidator: Validator = {
  name: "pii-redact",
  check(text: string): ValidatorResult | undefined {
    let redacted = text;
    let count = 0;
    const hitTypes: string[] = [];
    for (const [type, pattern] of Object.entries(PII_PATTERNS)) {
      const matches = text.match(pattern);
      if (matches && matches.length > 0) {
        count += matches.length;
        hitTypes.push(type);
        redacted = redacted.replace(pattern, `[REDACTED_${type.toUpperCase()}]`);
      }
    }
    if (count === 0) return undefined;
    return { action: "redact", category: "pii", redactedText: redacted, count, detail: hitTypes.join(", ") };
  },
};

const SECRET_PATTERNS: Record<string, RegExp> = {
  "openai-key": /\bsk-[A-Za-z0-9]{20,}\b/g,
  "generic-bearer": /\bBearer\s+[A-Za-z0-9._-]{20,}\b/g,
  "aws-access-key": /\bAKIA[0-9A-Z]{16}\b/g,
  "github-token": /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g,
  "private-key-block": /-----BEGIN [A-Z ]*PRIVATE KEY-----/g,
};

/** Catches API-key/token/credential shapes leaking into a response, à la Guardrails' secret-leak checks. */
export const secretLeakValidator: Validator = {
  name: "secret-leak",
  check(text: string): ValidatorResult | undefined {
    let redacted = text;
    let count = 0;
    const hitTypes: string[] = [];
    for (const [type, pattern] of Object.entries(SECRET_PATTERNS)) {
      const matches = text.match(pattern);
      if (matches && matches.length > 0) {
        count += matches.length;
        hitTypes.push(type);
        redacted = redacted.replace(pattern, "[REDACTED_SECRET]");
      }
    }
    if (count === 0) return undefined;
    return { action: "redact", category: "secret-leak", redactedText: redacted, count, detail: hitTypes.join(", ") };
  },
};

const INJECTION_PATTERNS: RegExp[] = [
  /ignore (all |any )?(previous|prior|above) instructions/i,
  /disregard (all |any )?(previous|prior|above)/i,
  /you are now (in )?(dan|developer mode|jailbreak)/i,
  /pretend (that )?you have no (restrictions|rules|guidelines)/i,
  /reveal your (system prompt|instructions)/i,
  /act as if you have no (content policy|filter)/i,
];

/** NeMo-style input rail: heuristic prompt-injection / jailbreak detection, blocks (not redacts) by default. */
export const promptInjectionValidator: Validator = {
  name: "prompt-injection",
  check(text: string): ValidatorResult | undefined {
    for (const pattern of INJECTION_PATTERNS) {
      if (pattern.test(text)) {
        return { action: "block", category: "prompt-injection", detail: `matched pattern: ${pattern.source}` };
      }
    }
    return undefined;
  },
};

export const DEFAULT_INPUT_VALIDATORS: Validator[] = [promptInjectionValidator];
export const DEFAULT_OUTPUT_VALIDATORS: Validator[] = [piiRedactValidator, secretLeakValidator];

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

export interface GuardrailEngineOptions {
  enabled?: boolean;
  inputValidators?: Validator[];
  outputValidators?: Validator[];
}

export class GuardrailEngine {
  readonly enabled: boolean;
  private readonly inputValidators: Validator[];
  private readonly outputValidators: Validator[];

  constructor(options: GuardrailEngineOptions = {}) {
    this.enabled = options.enabled ?? true;
    this.inputValidators = options.inputValidators ?? DEFAULT_INPUT_VALIDATORS;
    this.outputValidators = options.outputValidators ?? DEFAULT_OUTPUT_VALIDATORS;
  }

  /** Input rail: run before a request is sent to any model. Blocking findings should abort the call. */
  checkInput(text: string): GuardrailReport {
    return this.run(text, this.inputValidators);
  }

  /** Output rail: run on a model's response before it's handed back to the caller. Redacts in place. */
  checkOutput(text: string): GuardrailReport {
    return this.run(text, this.outputValidators);
  }

  private run(text: string, validators: Validator[]): GuardrailReport {
    if (!this.enabled) return { safe: true, text, findings: [] };

    let current = text;
    const findings: GuardrailFinding[] = [];
    let blocked = false;

    for (const validator of validators) {
      const result = validator.check(current);
      if (!result) continue;
      findings.push({ validator: validator.name, category: result.category, action: result.action, count: result.count, detail: result.detail });
      if (result.action === "redact" && result.redactedText !== undefined) {
        current = result.redactedText;
      } else if (result.action === "block") {
        blocked = true;
      }
    }

    return { safe: !blocked, text: current, findings };
  }
}
