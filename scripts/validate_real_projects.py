#!/usr/bin/env python3
"""Run the same recovery demo on existing clean checkouts of two real projects.

Install editable project packages and their test dependencies first. This script
intentionally mutates one source file, verifies actual upstream tests and mypy,
then repairs it to the original content plus an explanatory comment. It leaves
evidence and the final verified comment in the disposable validation checkout.
Never point this at your working repository.
"""
import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from demo import run_demo


async def validate(parent):
    reports = []
    cases = [
        ("itsdangerous", "src/itsdangerous/encoding.py", 'return base64.urlsafe_b64encode(string).rstrip(b"=")',
         'return base64.urlsafe_b64encode(string)', "# URL-safe tokens omit base64 padding."),
        ("click", "src/click/utils.py", 'return " ".join(words)  # no truncation needed',
         'return "BROKEN " + " ".join(words)  # injected faulty change', "# Preserve unchanged help when no truncation is needed."),
    ]
    for name, filename, original, broken, comment in cases:
        root = (parent / name).resolve()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
        if status:
            raise RuntimeError(f"{root} must be clean before this fault-injection run")
        content = (root / filename).read_text()
        if content.count(original) != 1:
            raise RuntimeError(f"Expected source marker not unique in {filename}")
        # Keep the original behavior after recovery; the comment makes the final diff inspectable.
        indent = next(line[:len(line) - len(line.lstrip())] for line in content.splitlines() if original in line)
        repaired = content.replace(original, comment + "\n" + indent + original)
        print(f"Running real tests and typecheck under supervision: {name}", flush=True)
        report = await run_demo(root, filename, content.replace(original, broken), repaired)
        reports.append(report)
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent", type=Path, help="directory containing clean itsdangerous and click git clones")
    parser.add_argument("--output", type=Path, default=Path("docs/real-project-results.json"))
    args = parser.parse_args()
    result = asyncio.run(validate(args.parent))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for report in result:
        print(report["project"], report["state"], report["elapsed_seconds"], "seconds")
