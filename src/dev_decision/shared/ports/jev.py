from typing import Any, Protocol


class JevClient(Protocol):
    mode: str

    async def decide(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> dict[str, Any]: ...
