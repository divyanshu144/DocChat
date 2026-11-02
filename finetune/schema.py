"""Typed records for the fine-tune data: the source manifest, its hash lock, and training examples."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# "excluded" documents stay in the manifest for the record but are used for nothing (see check_documents.py).
Split = Literal["train", "validation", "heldout", "excluded"]

# Evaluation evidence that must never be used for training. The working-time PDF has no public URL in the
# repo, so the n-gram check in decontaminate.py is what protects against it; these are the URL-level guards.
FORBIDDEN_URL_PARTS = ("wikipedia.org/wiki/Retrieval-augmented_generation",)
# The existing evaluation is about working-time rules. Keep that topic out of training documents.
FORBIDDEN_TITLE_WORDS = ("working time", "working hours", "night work", "rest break", "retrieval-augmented")


class SourceDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,80}$")
    title: str = Field(min_length=1)
    kind: Literal["govuk_guide", "pdf"]
    url: str
    licence: str = Field(min_length=3)
    licence_url: str
    split: Split
    note: str = ""

    @field_validator("url", "licence_url")
    @classmethod
    def https_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("must be an http(s) URL without credentials")
        return value

    @model_validator(mode="after")
    def not_evaluation_evidence(self):
        if any(part.lower() in self.url.lower() for part in FORBIDDEN_URL_PARTS):
            raise ValueError("this URL is evaluation evidence and cannot be a fine-tune source")
        if any(word in self.title.lower() for word in FORBIDDEN_TITLE_WORDS):
            raise ValueError("this topic is evaluation evidence and cannot be a fine-tune source")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    documents: list[SourceDoc] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        ids = [d.id for d in self.documents]
        urls = [d.url.lower().rstrip("/") for d in self.documents]
        if len(set(ids)) != len(ids):
            raise ValueError("document ids must be unique")
        if len(set(urls)) != len(urls):
            raise ValueError("document URLs must be unique, so one document cannot sit in two splits")
        return self

    def by_split(self, split: Split) -> list[SourceDoc]:
        return [d for d in self.documents if d.split == split]


class LockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=1)
    retrieved_at: str


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str


class TrainingExample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    split: Literal["train", "validation"]
    kind: Literal["answerable", "abstain"]
    doc_ids: list[str] = Field(min_length=1)
    messages: list[Message]
    teacher: str = Field(min_length=1)

    @staticmethod
    def make_id(messages: list[dict]) -> str:
        return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]

    @property
    def system(self) -> str:
        return self.messages[0].content

    @property
    def question(self) -> str:
        return self.messages[1].content

    @property
    def answer(self) -> str:
        return self.messages[2].content


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]
