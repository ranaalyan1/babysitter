"""Entry point: python -m babysitter (with src/ on PYTHONPATH)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
