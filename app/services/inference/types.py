from dataclasses import dataclass, field
from typing import Protocol, AsyncIterator


@dataclass(frozen=True)
class GenerationRequest:
    model: str
    messages: list[dict]
    max_tokens: int = 1024
    temperature: float | None = None

    def __post_init__(self):
        if not self.model.strip():
            raise ValueError("LOCAL_CHAT_MODEL must be configured")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")


@dataclass(frozen=True)
class GenerationResult:
    text: str = ""
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    request_id: str | None = None


class InferenceBackend(Protocol):
    async def complete(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest, *, include_usage: bool = True
               ) -> AsyncIterator[GenerationResult]: ...
