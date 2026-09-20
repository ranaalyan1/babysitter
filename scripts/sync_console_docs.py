#!/usr/bin/env python3
"""Copy the public guides into the wheel for offline console documentation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = {
    "getting-started": ("Getting started", "docs/GETTING_STARTED.md"),
    "console": ("Using the local console", "docs/CONSOLE.md"),
    "claude-code": ("Claude Code integration", "docs/CLAUDE_CODE.md"),
    "codex": ("Codex integration", "docs/CODEX.md"),
    "opencode": ("OpenCode integration", "docs/OPENCODE.md"),
    "validation": ("Measured results & limitations", "docs/VALIDATION.md"),
    "brand": ("Brand & design system", "docs/BRAND.md"),
}


def main():
    destination = ROOT / "aletheia" / "web" / "guides"
    destination.mkdir(exist_ok=True)
    for slug, (_, source) in GUIDES.items():
        (destination / (slug + ".md")).write_text((ROOT / source).read_text())
    (destination / "manifest.json").write_text(json.dumps({slug: {"title": title, "source": source} for slug, (title, source) in GUIDES.items()}, indent=2) + '\n')
    print(f"Synced {len(GUIDES)} offline guides")


if __name__ == '__main__':
    main()
