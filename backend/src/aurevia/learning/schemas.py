"""Learning API bodies (WP-12.3). Imports arrive as JSON lines or as CSV text."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aurevia.learning.models import LineSpeaker, SourceOutcome, SourceType

MAX_LINES = 5000


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LineIn(_Body):
    speaker: LineSpeaker
    text: str = Field(min_length=1, max_length=4000)
    start_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    end_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    # Word timings, numbers only: [[start_ms, end_ms], ...] (WP-12.1 provides these).
    word_times_ms: list[tuple[int, int]] | None = Field(default=None, max_length=4000)

    def has_timing(self) -> bool:
        return self.start_ms is not None or self.end_ms is not None or bool(self.word_times_ms)


class SourceImportIn(_Body):
    source_type: SourceType
    title: str = Field(min_length=1, max_length=200)
    language: str = Field(min_length=2, max_length=10, pattern=r"^[a-zA-Z]{2,3}(-[A-Za-z]{2})?$")
    industry: str | None = Field(default=None, max_length=100)
    outcome: SourceOutcome = SourceOutcome.UNKNOWN
    # The caller's permission is on file (WP-12.0). Required: nothing is imported without it.
    caller_permission_confirmed: bool
    lines: list[LineIn] | None = Field(default=None, max_length=MAX_LINES)
    # Or CSV with a header row: speaker,text[,start_ms,end_ms]
    lines_csv: str | None = Field(default=None, max_length=2_000_000)

    @model_validator(mode="after")
    def _check(self) -> SourceImportIn:
        if not self.caller_permission_confirmed:
            raise ValueError("the caller's permission must be on file before importing")
        if (self.lines is None) == (self.lines_csv is None):
            raise ValueError("give either lines or lines_csv")
        if self.lines_csv is not None:
            self.lines = parse_csv(self.lines_csv)
            self.lines_csv = None
        if not self.lines:
            raise ValueError("the transcript has no lines")
        if self.source_type == SourceType.TALK and any(line.has_timing() for line in self.lines):
            # A talk never feeds the timing profile: refuse timings rather than drop them.
            raise ValueError("a talk source has no timings; import it without them")
        return self


def parse_csv(text: str) -> list[LineIn]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"speaker", "text"} <= set(reader.fieldnames):
        raise ValueError("the CSV needs a header row with at least speaker and text")
    extra = set(reader.fieldnames) - {"speaker", "text", "start_ms", "end_ms"}
    if extra:
        raise ValueError(f"unknown CSV columns: {', '.join(sorted(extra))}")
    lines = []
    for number, row in enumerate(reader, start=2):
        if len(lines) >= MAX_LINES:
            raise ValueError(f"at most {MAX_LINES} lines")
        values: dict[str, Any] = {"speaker": row["speaker"], "text": row["text"]}
        for name in ("start_ms", "end_ms"):
            if row.get(name):
                try:
                    values[name] = int(row[name])
                except ValueError as exc:
                    raise ValueError(f"line {number}: {name} must be a whole number") from exc
        lines.append(LineIn.model_validate(values))
    return lines


class SourceOut(BaseModel):
    id: uuid.UUID
    source_type: SourceType
    title: str
    language: str
    industry: str | None
    outcome: SourceOutcome
    line_count: int
    redaction_counts: dict[str, int]
    created_at: datetime


class LineOut(BaseModel):
    seq: int
    speaker: LineSpeaker
    text: str
    start_ms: int | None
    end_ms: int | None


class SourceDetailOut(SourceOut):
    lines: list[LineOut]
