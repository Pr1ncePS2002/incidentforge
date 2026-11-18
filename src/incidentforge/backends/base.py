"""generator backend contract. owner: phase 2."""

from typing import Any, Protocol


class Backend(Protocol):
    name: str

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        """return a json object matching schema; raise on failure."""
        ...
