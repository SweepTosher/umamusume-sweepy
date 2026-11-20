from __future__ import annotations

import os
from pathlib import Path
import sys


def _venv_python() -> str:
    root = Path(__file__).resolve().parent
    for relative in ("bin/python", "Scripts/python.exe"):
        candidate = root / ".venv" / relative
        if candidate.is_file():
            return str(candidate)
    return ""


def main() -> int:
    target = _venv_python()
    if target:
        current = os.path.normpath(sys.prefix)
        wanted = os.path.normpath(str(Path(target).parent.parent))
        if current != wanted:
            os.execv(target, [target, str(Path(__file__).resolve()), *sys.argv[1:]])
    from sweepy.cli import main as run
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
