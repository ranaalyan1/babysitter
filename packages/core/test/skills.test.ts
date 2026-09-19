import { describe, expect, it } from "vitest";
import { parseSkillFile } from "../src/skills/loader.js";

describe("Skill parsing (Agent Skills / SKILL.md spec)", () => {
  it("parses valid frontmatter and body", () => {
    const raw = `---
name: my-skill
description: Does a thing and explains when to use it in enough detail for validation.
tags: [a, b]
allowed-tools: filesystem.read filesystem.write
---
# Instructions
Do the thing.`;
    const descriptor = parseSkillFile(raw, "/skills/my-skill");
    expect(descriptor.metadata.name).toBe("my-skill");
    expect(descriptor.metadata.tags).toEqual(["a", "b"]);
    expect(descriptor.metadata.allowedTools).toEqual(["filesystem.read", "filesystem.write"]);
    expect(descriptor.instructions).toContain("Do the thing.");
    expect(descriptor.issues.filter((i) => i.level === "error")).toHaveLength(0);
  });

  it("flags a missing frontmatter block as an error", () => {
    const descriptor = parseSkillFile("# just a heading, no frontmatter", "/skills/bad");
    expect(descriptor.issues.some((i) => i.level === "error")).toBe(true);
  });

  it("flags an invalid name (uppercase/underscore) per the spec", () => {
    const raw = `---
name: My_Bad_Name
description: A description that is definitely long enough to pass the length check.
---
Body`;
    const descriptor = parseSkillFile(raw, "/skills/bad-name");
    expect(descriptor.issues.some((i) => i.level === "error" && i.message.includes("lowercase"))).toBe(true);
  });

  it("flags a missing description as an error", () => {
    const raw = `---
name: valid-name
---
Body`;
    const descriptor = parseSkillFile(raw, "/skills/no-desc");
    expect(descriptor.issues.some((i) => i.level === "error" && i.message.includes("description"))).toBe(true);
  });

  it("warns (but does not error) on a very short description", () => {
    const raw = `---
name: valid-name
description: too short
---
Body`;
    const descriptor = parseSkillFile(raw, "/skills/short-desc");
    expect(descriptor.issues.some((i) => i.level === "warning")).toBe(true);
    expect(descriptor.issues.some((i) => i.level === "error")).toBe(false);
  });
});
