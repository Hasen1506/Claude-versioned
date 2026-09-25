"""Print the API's OpenAPI document (used to generate the web client's TypeScript types)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scp.api.app import app  # noqa: E402

print(json.dumps(app.openapi(), indent=1))
