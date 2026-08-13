import csv
import io
from collections.abc import Sequence
from typing import Any

from app.models.mapping import BatchRowResult

DEFAULT_MAX_ALTERNATIVES = 5

_BASE_MAPPING_COLUMNS = [
    "mapped_code",
    "mapped_term",
    "mapped_ontology",
    "confidence",
    "logic_type",
    "suggested_explanation",
]
_DECISION_COLUMN = "decision"


def build_batch_rows_csv(
    rows: Sequence[BatchRowResult],
    *,
    max_alternatives: int = DEFAULT_MAX_ALTERNATIVES,
) -> str:
    """Build the enriched batch CSV from current row results."""
    source_columns = _source_columns(rows)
    include_requested_target = _include_requested_target_column(rows, source_columns)
    raw_generated_columns = _raw_generated_column_names(
        max_alternatives,
        include_requested_target=include_requested_target,
    )
    generated_columns = [
        _avoid_collision(column, source_columns) for column in raw_generated_columns
    ]
    headers = [*source_columns, *generated_columns]
    export_rows = [
        _export_row(
            row,
            source_columns,
            generated_columns,
            raw_generated_columns,
            max_alternatives,
        )
        for row in rows
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(export_rows)
    return buf.getvalue()


def _source_columns(rows: Sequence[BatchRowResult]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        row_columns = row.original_columns or list(row.original_row.keys())
        if not row_columns and not row.original_row:
            row_columns = _legacy_source_columns(row)
        for column in row_columns:
            if column not in seen:
                columns.append(column)
                seen.add(column)
        for column in row.original_row:
            if column not in seen:
                columns.append(column)
                seen.add(column)
    return columns


def _legacy_source_columns(row: BatchRowResult) -> list[str]:
    columns = ["field_name"]
    if row.label is not None:
        columns.append("label")
    if row.source_description is not None:
        columns.append("source_description")
    if row.requested_target_ontology is not None:
        columns.append("target_ontology")
    return columns


def _include_requested_target_column(
    rows: Sequence[BatchRowResult],
    source_columns: Sequence[str],
) -> bool:
    return "target_ontology" not in source_columns and any(
        row.requested_target_ontology for row in rows
    )


def _avoid_collision(column: str, source_columns: Sequence[str]) -> str:
    if column not in source_columns:
        return column
    candidate = f"bridge_{column}"
    while candidate in source_columns:
        candidate = f"bridge_{candidate}"
    return candidate


def _export_row(
    row: BatchRowResult,
    source_columns: Sequence[str],
    generated_columns: Sequence[str],
    raw_generated_columns: Sequence[str],
    max_alternatives: int,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    source_values = _source_values(row)
    for column in source_columns:
        values[column] = source_values.get(column, "")

    generated_values = _raw_generated_values(row, max_alternatives)
    for header, raw_name in zip(generated_columns, raw_generated_columns, strict=True):
        values[header] = generated_values.get(raw_name, "")
    return values


def _source_values(row: BatchRowResult) -> dict[str, Any]:
    if row.original_row:
        return dict(row.original_row)

    values: dict[str, Any] = {"field_name": row.field_name}
    if row.label is not None:
        values["label"] = row.label
    if row.source_description is not None:
        values["source_description"] = row.source_description
    if row.requested_target_ontology is not None:
        values["target_ontology"] = row.requested_target_ontology
    return values


def _raw_generated_column_names(
    max_alternatives: int,
    *,
    include_requested_target: bool,
) -> list[str]:
    raw = list(_BASE_MAPPING_COLUMNS)
    if include_requested_target:
        raw.insert(0, "target_ontology")

    for index in range(1, max_alternatives + 1):
        raw.extend(
            [
                f"alternative_{index}_code",
                f"alternative_{index}_term",
                f"alternative_{index}_ontology",
                f"alternative_{index}_confidence",
                f"alternative_{index}_explanation",
            ]
        )
    raw.append(_DECISION_COLUMN)
    return raw


def _raw_generated_values(
    row: BatchRowResult,
    max_alternatives: int,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "target_ontology": row.requested_target_ontology or "",
        "mapped_code": row.suggested_code,
        "mapped_term": row.suggested_term,
        "mapped_ontology": row.ontology,
        "confidence": _format_confidence(row.confidence),
        "logic_type": row.logic_type,
        "suggested_explanation": row.notes or "",
        "decision": row.decision,
    }
    for index in range(1, max_alternatives + 1):
        alt = row.alternatives[index - 1] if index <= len(row.alternatives) else None
        values[f"alternative_{index}_code"] = alt.code if alt else ""
        values[f"alternative_{index}_term"] = alt.term if alt else ""
        values[f"alternative_{index}_ontology"] = alt.ontology if alt else ""
        values[f"alternative_{index}_confidence"] = (
            _format_confidence(alt.confidence) if alt else ""
        )
        values[f"alternative_{index}_explanation"] = (
            alt.explanation or "" if alt else ""
        )
    return values


def _format_confidence(confidence: float) -> str:
    return f"{confidence:.0%}"
