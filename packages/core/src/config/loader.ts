import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";
import type { Test0FileConfig } from "./schema.js";

export const CONFIG_FILE_NAMES = ["test0.config.yaml", "test0.config.yml"];

/** Loads `test0.config.yaml` (or `.yml`) from a project directory, if present. */
export async function loadFileConfig(projectDir: string): Promise<Test0FileConfig | undefined> {
  for (const name of CONFIG_FILE_NAMES) {
    try {
      const raw = await readFile(join(projectDir, name), "utf-8");
      return (parseYaml(raw) as Test0FileConfig) ?? {};
    } catch {
      continue;
    }
  }
  return undefined;
}
