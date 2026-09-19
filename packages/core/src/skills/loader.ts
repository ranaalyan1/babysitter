import { readFile, readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";
import type { SkillDescriptor, SkillMetadata, SkillSummary, SkillValidationIssue } from "../types/index.js";

const NAME_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const MAX_NAME_LENGTH = 64;
const MAX_DESCRIPTION_LENGTH = 1024;

/**
 * Skill System (test0 V5 §6), implementing the open Agent Skills / SKILL.md
 * specification (see https://agentskills.io/specification and Anthropic's
 * "Agent Skills" format) rather than a bespoke schema. This buys test0
 * compatibility with the growing ecosystem of skills authored for Claude
 * Code and other spec-compliant agents.
 *
 * Progressive disclosure, per the spec:
 *   Level 1 — name + description only, loaded for every skill at session
 *             start (cheap, ~100 tokens each). See `SkillRegistry.summaries()`.
 *   Level 2 — the full SKILL.md body, loaded once an agent decides a
 *             skill is relevant. See `SkillRegistry.get()`.
 *   Level 3 — referenced files (scripts/, references/, assets/) loaded
 *             lazily by the agent as instructed inside the body; test0
 *             does not eagerly read these.
 *
 * Directory layout per skill:
 *   skills/<name>/
 *     SKILL.md       (required)
 *     scripts/       (optional, executable helpers)
 *     references/    (optional, loaded only when the body points to them)
 *     assets/        (optional, templates/images/etc.)
 */
export class SkillRegistry {
  private skills = new Map<string, SkillDescriptor>();
  private readonly skillsDirs: string[];

  constructor(skillsDir: string | string[]) {
    this.skillsDirs = Array.isArray(skillsDir) ? skillsDir : [skillsDir];
  }

  async loadAll(): Promise<SkillDescriptor[]> {
    this.skills.clear();
    for (const dir of this.skillsDirs) {
      await this.loadDir(dir);
    }
    return this.list();
  }

  private async loadDir(skillsDir: string): Promise<void> {
    const entries = await readdir(skillsDir).catch(() => []);

    for (const entry of entries) {
      const dirPath = join(skillsDir, entry);
      try {
        const s = await stat(dirPath);
        if (!s.isDirectory()) continue;
      } catch {
        continue;
      }
      const skillFile = join(dirPath, "SKILL.md");
      try {
        const raw = await readFile(skillFile, "utf-8");
        const descriptor = parseSkillFile(raw, dirPath);
        this.skills.set(descriptor.metadata.name, descriptor);
      } catch {
        // No SKILL.md in this directory; skip.
        continue;
      }
    }
  }

  /** Level 1 view for every installed skill — cheap to hand to a planning model. */
  summaries(): SkillSummary[] {
    return this.list().map((s) => ({
      name: s.metadata.name,
      description: s.metadata.description,
      tags: s.metadata.tags ?? [],
    }));
  }

  list(): SkillDescriptor[] {
    return [...this.skills.values()];
  }

  get(name: string): SkillDescriptor | undefined {
    return this.skills.get(name);
  }

  findByTag(tag: string): SkillDescriptor[] {
    return this.list().filter((s) => (s.metadata.tags ?? []).includes(tag));
  }

  install(descriptor: SkillDescriptor): void {
    this.skills.set(descriptor.metadata.name, descriptor);
  }

  remove(name: string): boolean {
    return this.skills.delete(name);
  }
}

export function parseSkillFile(raw: string, path: string): SkillDescriptor {
  const frontmatterMatch = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  const issues: SkillValidationIssue[] = [];

  if (!frontmatterMatch) {
    issues.push({ level: "error", message: "SKILL.md is missing required YAML frontmatter (--- ... ---)." });
    return {
      metadata: { name: path.split("/").pop() ?? "unknown", description: "" },
      path,
      instructions: raw.trim(),
      issues,
    };
  }

  const [, frontmatterText, body] = frontmatterMatch;
  const metadata = parseFrontmatter(frontmatterText, issues);
  validateMetadata(metadata, issues);

  return { metadata, path, instructions: body.trim(), issues };
}

function parseFrontmatter(text: string, issues: SkillValidationIssue[]): SkillMetadata {
  let data: Record<string, unknown> = {};
  try {
    data = (parseYaml(text) as Record<string, unknown>) ?? {};
  } catch (err) {
    issues.push({ level: "error", message: `Failed to parse frontmatter YAML: ${err instanceof Error ? err.message : err}` });
  }

  const toStringArray = (v: unknown): string[] | undefined => {
    if (Array.isArray(v)) return v.map(String);
    if (typeof v === "string" && v.trim()) return v.split(/\s+/); // spec allows space-separated allowed-tools
    return undefined;
  };

  return {
    name: String(data.name ?? path_basename_fallback()),
    description: String(data.description ?? ""),
    license: data.license ? String(data.license) : undefined,
    compatibility: data.compatibility ? String(data.compatibility) : undefined,
    metadata: isStringRecord(data.metadata) ? data.metadata : undefined,
    allowedTools: toStringArray(data["allowed-tools"] ?? data.allowedTools),
    version: data.version ? String(data.version) : "1.0.0",
    tags: toStringArray(data.tags) ?? [],
    dependencies: toStringArray(data.dependencies),
    author: data.author ? String(data.author) : undefined,
  };

  function path_basename_fallback(): string {
    return "unknown";
  }
}

function isStringRecord(v: unknown): v is Record<string, string> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function validateMetadata(metadata: SkillMetadata, issues: SkillValidationIssue[]): void {
  if (!metadata.name) {
    issues.push({ level: "error", message: "Missing required 'name' field." });
  } else {
    if (metadata.name.length > MAX_NAME_LENGTH) {
      issues.push({ level: "error", message: `'name' exceeds ${MAX_NAME_LENGTH} characters.` });
    }
    if (!NAME_PATTERN.test(metadata.name)) {
      issues.push({
        level: "error",
        message: "'name' must be lowercase letters, numbers, and hyphens only, and must not start/end with a hyphen.",
      });
    }
  }

  if (!metadata.description) {
    issues.push({ level: "error", message: "Missing required 'description' field." });
  } else if (metadata.description.length > MAX_DESCRIPTION_LENGTH) {
    issues.push({ level: "error", message: `'description' exceeds ${MAX_DESCRIPTION_LENGTH} characters.` });
  } else if (metadata.description.length < 20) {
    issues.push({
      level: "warning",
      message: "'description' is very short — the spec recommends describing both what the skill does and when to use it.",
    });
  }

  if (/[<>]/.test(JSON.stringify(metadata))) {
    issues.push({
      level: "warning",
      message: "Frontmatter contains angle brackets, which the spec warns can inject unintended instructions.",
    });
  }
}
