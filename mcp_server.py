from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))
    from mcp_tools.server import run_server

    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

