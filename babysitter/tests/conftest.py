"""Pytest bootstrap: put src/ on sys.path so tests import babysitter."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
