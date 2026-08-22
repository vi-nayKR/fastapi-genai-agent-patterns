"""Print the generated OpenAPI document for client generation or review."""

import json

from agent_patterns.app import create_app


def main() -> None:
    document = create_app().openapi()
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
