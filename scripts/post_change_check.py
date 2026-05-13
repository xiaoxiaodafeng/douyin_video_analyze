from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> int:
    print('> ' + ' '.join(cmd))
    proc = subprocess.run(cmd)
    return proc.returncode


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    py = root / '.venv' / 'Scripts' / 'python.exe'
    if not py.exists():
        py = Path(sys.executable)

    checks = [
        [str(py), '-m', 'compileall', str(root / 'app')],
        [str(py), '-c', 'import app.main; print("app.main import ok")'],
    ]

    for cmd in checks:
        code = run(cmd)
        if code != 0:
            print(f'check failed: exit={code}')
            return code

    print('all checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
