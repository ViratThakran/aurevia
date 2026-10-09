"""Importing leads from CSV (Phase 8). Every row is validated like a lead created by hand.

Columns (header row required): ``name`` (required), ``phone``, ``email``, ``company``. Valid rows
are created in one transaction and one audit event; invalid rows are reported by line number
and skipped.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import AureviaError
from aurevia.identity.audit import record_audit_event
from aurevia.memory.models import Lead, LeadStatus
from aurevia.memory.schemas import LeadIn

MAX_ROWS = 5000
COLUMNS = ("name", "phone", "email", "company")


class InvalidCsvError(AureviaError):
    status_code = 422
    code = "invalid_csv"


@dataclass
class ImportResult:
    lead_ids: list[uuid.UUID] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)


async def import_leads(
    session: AsyncSession, tenant_id: uuid.UUID, csv_text: str, actor: uuid.UUID
) -> ImportResult:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    if "name" not in header:
        raise InvalidCsvError("The first row must be a header with at least a 'name' column")
    unknown = [h for h in header if h not in COLUMNS]
    if unknown:
        raise InvalidCsvError(f"Unknown columns: {', '.join(unknown)}")
    reader.fieldnames = header
    result = ImportResult()
    leads: list[Lead] = []
    for line, row in enumerate(reader, start=2):
        if line - 1 > MAX_ROWS:
            raise InvalidCsvError(f"At most {MAX_ROWS} rows per import")
        values = {k: (v or "").strip() or None for k, v in row.items() if k in COLUMNS}
        try:
            fields = LeadIn.model_validate(values)
        except ValidationError as exc:
            first = exc.errors()[0]
            result.errors.append(
                {
                    "line": line,
                    "field": ".".join(str(p) for p in first["loc"]),
                    "error": first["msg"],
                }
            )
            continue
        lead = Lead(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status=LeadStatus.ACTIVE,
            name=fields.name,
            phone=fields.phone,
            email=str(fields.email).lower() if fields.email else None,
            company=fields.company,
        )
        leads.append(lead)
        result.lead_ids.append(lead.id)
    if leads:
        session.add_all(leads)
        record_audit_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=actor,
            action="leads.imported",
            target_type="lead",
            details={"created": len(leads), "rejected": len(result.errors)},
        )
        await session.commit()
    return result
