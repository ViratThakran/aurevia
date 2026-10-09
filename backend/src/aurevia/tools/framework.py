"""Tool & Action Framework: the only path from a model's request to a real side effect.

    model ToolCall -> known tool? -> schema validation -> business rules -> action
                   -> ToolExecution audit row (same transaction) -> ToolResult for the model

A result is ``ok`` only if the action actually happened and was committed. Anything else
(unknown tool, bad arguments, a rule that said no, an exception) comes back as an error the
model must not present as success.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.db.session import set_tenant_context
from aurevia.memory.models import Lead
from aurevia.providers.model import ToolCall, ToolResult, ToolSpec
from aurevia.sales.models import ToolExecution, ToolStatus
from aurevia.voice.models import Call

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    session: AsyncSession
    tenant_id: uuid.UUID
    call: Call
    lead: Lead | None
    now: datetime  # timezone-aware


@dataclass(frozen=True)
class ToolOutcome:
    status: ToolStatus
    message: str  # plain words for the model to relay honestly
    data: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    @classmethod
    def ok(cls, message: str, **data: Any) -> ToolOutcome:
        return cls(ToolStatus.OK, message, data)

    @classmethod
    def rejected(cls, code: str, message: str, **data: Any) -> ToolOutcome:
        return cls(ToolStatus.REJECTED, message, data, error_code=code)


class Tool[ArgsT: BaseModel](ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]
    requires_lead: ClassVar[bool] = True
    # Only records something; the result never changes what the agent should say. When the
    # model has already spoken alongside such calls and they succeed, no follow-up model
    # round is needed (it would cost a full model round trip of silence).
    record_only: ClassVar[bool] = False

    def spec(self) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)

    @abstractmethod
    async def run(self, ctx: ToolContext, args: ArgsT) -> ToolOutcome: ...


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool[Any]]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> Tool[Any] | None:
        return self._tools.get(name)

    def is_record_only(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool is not None and tool.record_only

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec() for tool in self._tools.values())


def idempotency_key(call_id: uuid.UUID, tool: str, arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{call_id}|{tool}|{canonical}".encode()).hexdigest()


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        self._registry = registry
        self._ctx = ctx

    def needs_follow_up(self, results: Sequence[ToolResult]) -> bool:
        """Whether the model must see these results before the turn can end."""
        return any(r.is_error or not self._registry.is_record_only(r.name) for r in results)

    async def execute(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        session = self._ctx.session
        key = idempotency_key(self._ctx.call.id, call.name, call.arguments)

        previous = await session.scalar(
            select(ToolExecution).where(
                ToolExecution.idempotency_key == key,
                ToolExecution.tenant_id == self._ctx.tenant_id,
            )
        )
        if previous is not None:  # the same request again: report, never act twice
            return _result(call, ToolStatus(previous.status), previous.result)

        outcome = await self._run(call)
        payload = _payload(outcome)
        session.add(
            ToolExecution(
                tenant_id=self._ctx.tenant_id,
                call_id=self._ctx.call.id,
                tool=call.name[:50],
                idempotency_key=key,
                status=outcome.status,
                arguments=dict(call.arguments),
                result=payload,
                error_code=outcome.error_code,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )
        await session.commit()  # the action and its audit row, together
        # SET LOCAL tenant context ends with the transaction: restore it for what follows.
        await set_tenant_context(session, self._ctx.tenant_id)
        return _result(call, outcome.status, payload)

    async def _run(self, call: ToolCall) -> ToolOutcome:
        tool = self._registry.get(call.name)
        if tool is None:
            return ToolOutcome.rejected("unknown_tool", f"There is no tool called {call.name!r}.")
        try:
            args = tool.args_model.model_validate(dict(call.arguments))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}"
                for err in exc.errors()[:5]
            )
            return ToolOutcome.rejected("invalid_arguments", f"Invalid arguments: {problems}")
        if tool.requires_lead and self._ctx.lead is None:
            return ToolOutcome.rejected(
                "no_lead", "This call is not linked to a lead, so nothing can be recorded."
            )
        try:
            async with self._ctx.session.begin_nested():  # roll back only this tool's writes
                return await tool.run(self._ctx, args)
        except IntegrityError:  # e.g. the slot was booked a moment ago
            return ToolOutcome.rejected(
                "conflict", "That could not be done because it conflicts with existing data."
            )
        except Exception:
            logger.exception("Tool failed", extra={"fields": {"tool": call.name}})
            return ToolOutcome(
                ToolStatus.FAILED,
                "Something went wrong and the action was NOT completed.",
                error_code="internal_error",
            )


def _payload(outcome: ToolOutcome) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": outcome.status == ToolStatus.OK,
        "status": outcome.status.value,
        "message": outcome.message,
    }
    if outcome.error_code:
        payload["error"] = outcome.error_code
    payload.update(json.loads(json.dumps(dict(outcome.data), default=str)))
    return payload


def _result(call: ToolCall, status: ToolStatus, payload: Mapping[str, Any]) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=dict(payload),
        is_error=status != ToolStatus.OK,
    )
