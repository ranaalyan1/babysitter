import { readFile, readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import type { SkillDescriptor, SkillMetadata } from "../types/index.js";

/**
 * Skill System (section 6).
 *
 * Skills live on disk as directories containing a SKILL.md file with
 * YAML-ish frontmatter metadata + free-form instructions body, mirroring
 * common SKILL.md-style agent workflows.
 *
 * Example:
 *   skills/python/SKILL.md
 *   ---
 *   name: python
 *   version: 1.0.0
 *   description: Python coding conventions and best practices
 *   tags: [coding, python]
 *   requiredTools: [terminal, filesystem]
 *   ---
 *   # Python Skill
 *   ...instructions...
 */
export class SkillRegistry {
  private skills = new Map<string, SkillDescriptor>();

  constructor(private readonly skillsDir: string) {}

  async loadAll(): Promise<SkillDescriptor[]> {
    this.skills.clear();
    let entries: string[] = [];
    try {
      entries = await readdir(this.skillsDir);
    } catch {
      return [];
    }

    for (const entry of entries) {
      const dirPath = join(this.skillsDir, entry);
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
    return this.list();
  }

  list(): SkillDescriptor[] {
    return [...this.skills.values()];
  }

  get(name: string): SkillDescriptor | undefined {
    return this.skills.get(name);
  }

  findByTag(tag: string): SkillDescriptor[] {
    return this.list().filter((s) => s.metadata.tags.includes(tag));
  }

  install(descriptor: SkillDescriptor): void {
    this.skills.set(descriptor.metadata.name, descriptor);
  }

  remove(name: string): boolean {
    return this.skills.delete(name);
  }
}

function parseSkillFile(raw: string, path: string): SkillDescriptor {
  const frontmatterMatch = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!frontmatterMatch) {
    // No frontmatter: treat entire file as instructions with minimal metadata.
    return {
      metadata: {
        name: path.split("/").pop() ?? "unknown",
        version: "0.0.0",
        description: "",
        tags: [],
      },
      path,
      instructions: raw,
    };
  }

  const [, frontmatter, body] = frontmatterMatch;
  const metadata = parseFrontmatter(frontmatter);
  return { metadata, path, instructions: body.trim() };
}

function parseFrontmatter(text: string): SkillMetadata {
  const lines = text.split("\n");
  const data: Record<string, unknown> = {};
  for (const line of lines) {
    const m = line.match(/^([a-zA-Z_]+):\s*(.*)$/);
    if (!m) continue;
    const [, key, rawValue] = m;
    data[key] = parseValue(rawValue.trim());
  }
  return {
    name: String(data.name ?? "unknown"),
    version: String(data.version ?? "0.0.0"),
    description: String(data.description ?? ""),
    tags: Array.isArray(data.tags) ? (data.tags as string[]) : [],
    requiredTools: Array.isArray(data.requiredTools) ? (data.requiredTools as string[]) : undefined,
    dependencies: Array.isArray(data.dependencies) ? (data.dependencies as string[]) : undefined,
    author: data.author ? String(data.author) : undefined,
  };
}

function parseValue(value: string): unknown {
  if (value.startsWith("[") && value.endsWith("]")) {
    return value
      .slice(1, -1)
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  }
  return value;
}
