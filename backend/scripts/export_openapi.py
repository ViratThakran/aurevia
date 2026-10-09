"""Write the API's OpenAPI schema (the dashboard generates its types from it).

uv run python scripts/export_openapi.py ../web/dashboard/openapi.json
"""

from __future__ import annotations

import json
import sys

from aurevia.config import Settings
from aurevia.main import create_app


def main(path: str) -> None:
    app = create_app(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(app.openapi(), indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
