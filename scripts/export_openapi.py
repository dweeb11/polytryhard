#!/usr/bin/env python3
"""Write FastAPI OpenAPI schema to ui/openapi/openapi.json for codegen and CI drift checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ["REQUIRE_DBS"] = "0"
os.environ["CONTROL_PLANE_TOKEN"] = "export-token"

from core.api.main import create_app  # noqa: E402
from core.settings import Settings  # noqa: E402


def main() -> None:
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="export-token",
    )
    app = create_app(settings)
    output = REPO_ROOT / "ui" / "openapi" / "openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
