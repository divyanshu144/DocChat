"""Versioned DocChat workload manifests, shared by capture and sustained replay."""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str


class WorkloadCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    split: Literal["development", "held_out"] = "development"
    category: Literal["document_qa", "summarisation", "long_context", "multi_document", "negative_control"]
    query: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    max_tokens: int = Field(default=1400, ge=1, le=65536)
    expected_evidence: list[str] = Field(default_factory=list)
    # Gold facts and actually retrieved gold chunks are capture-time evidence,
    # not model judgments. They support reviewer packs and retrieval-conditioned
    # answer-quality analysis without treating a miss as a generation failure.
    expected_facts: list[str] = Field(default_factory=list)
    evidence_retrieved: list[str] = Field(default_factory=list)


class Workloads(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    corpus_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cases: list[WorkloadCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Workload case IDs must be unique")
        return self

    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()


def load_workloads(path: Path, target: str) -> Workloads:
    workloads = Workloads.model_validate_json(path.read_text())
    if target == "replay" and any(not case.messages for case in workloads.cases):
        raise ValueError("Replay requires captured messages for every case; run prompt capture first")
    return workloads
