import csv
import io
import json
import logging
from enum import Enum
from pathlib import PurePath

import pandas as pd  # type: ignore[import-untyped]
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pandas.errors import EmptyDataError, ParserError  # type: ignore[import-untyped]

from app.models.mapping import BatchMappingResponse
from app.services.mapper_service import (
    cancel_batch_job,
    get_batch_job,
    promote_batch_alternative,
    start_batch_job,
    update_batch_decision,
)
from app.utils.ontology import (
    SUPPORTED_TARGET_ONTOLOGIES,
    normalize_target_ontologies,
    normalize_target_ontology_identifier,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_TARGET_ONTOLOGIES_ERROR = "target_ontologies_json must be a JSON array of strings"
_UNSUPPORTED_FILE_ERROR = "Unsupported file type. Upload a CSV, TSV, or XLSX file."
_TARGET_ONTOLOGY_COLUMN_MISSING_ERROR = (
    "The selected target ontology column was not found in the uploaded file."
)


class BatchFileFormat(str, Enum):
    CSV = ".csv"
    TSV = ".tsv"
    XLSX = ".xlsx"


def _detect_batch_file_format(filename: str) -> BatchFileFormat:
    suffix = PurePath(filename).suffix.lower()
    try:
        return BatchFileFormat(suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_UNSUPPORTED_FILE_ERROR) from exc


def _read_batch_dataframe(contents: bytes, filename: str) -> pd.DataFrame:
    file_format = _detect_batch_file_format(filename)
    buffer = io.BytesIO(contents)
    try:
        if file_format == BatchFileFormat.XLSX:
            df = pd.read_excel(buffer)
        elif file_format == BatchFileFormat.TSV:
            df = pd.read_csv(buffer, sep="\t", encoding="utf-8-sig")
        else:
            df = pd.read_csv(buffer, encoding="utf-8-sig")
    except EmptyDataError as exc:
        raise HTTPException(
            status_code=422,
            detail="The uploaded file must include a header row.",
        ) from exc
    except ParserError as exc:
        if file_format == BatchFileFormat.TSV:
            detail = (
                "We could not read this TSV file. Check that it is "
                "tab-separated and includes a header row."
            )
        elif file_format == BatchFileFormat.CSV:
            detail = (
                "We could not read this CSV file. Check that it is "
                "comma-separated and includes a header row."
            )
        else:
            detail = "We could not read this XLSX file. Check that it includes a header row."
        raise HTTPException(status_code=422, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"We could not read this {file_format.value[1:].upper()} file.",
        ) from exc

    if len(df.columns) == 0:
        raise HTTPException(
            status_code=422,
            detail="The uploaded file must include a header row.",
        )
    return df


def _parse_target_ontologies_json(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=_TARGET_ONTOLOGIES_ERROR) from exc

    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail=_TARGET_ONTOLOGIES_ERROR)

    try:
        return normalize_target_ontologies(parsed)
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=_TARGET_ONTOLOGIES_ERROR) from exc


def _format_target_ontology_value(value) -> str:
    if pd.isna(value):
        return "blank"
    text = str(value).strip()
    return f'"{text}"' if text else "blank"


def _validate_target_ontology_column(
    df: pd.DataFrame,
    target_ontology_column: str | None,
) -> list[str] | None:
    if not target_ontology_column:
        return None

    column = target_ontology_column.strip()
    if not column:
        return None
    if column not in df.columns:
        raise HTTPException(
            status_code=422,
            detail=_TARGET_ONTOLOGY_COLUMN_MISSING_ERROR,
        )

    normalized_values: list[str] = []
    invalid_rows: list[tuple[int, str]] = []
    for index, value in df[column].items():
        if pd.isna(value):
            invalid_rows.append((int(index) + 2, "blank"))
            continue

        raw = str(value).strip()
        normalized = normalize_target_ontology_identifier(raw)
        if not normalized or any(separator in raw for separator in [",", ";", "|"]):
            invalid_rows.append((int(index) + 2, _format_target_ontology_value(value)))
            continue

        normalized_values.append(normalized)

    if invalid_rows:
        examples = "\n".join(
            f"Row {row_number}: {invalid_value}"
            for row_number, invalid_value in invalid_rows[:10]
        )
        more = (
            f"\n...and {len(invalid_rows) - 10} more rows"
            if len(invalid_rows) > 10
            else ""
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"{len(invalid_rows)} rows have invalid target ontology values:\n"
                f"{examples}{more}\n"
                "Supported ontology identifiers: "
                f"{', '.join(SUPPORTED_TARGET_ONTOLOGIES)}"
            ),
        )

    return normalized_values


@router.post("/upload-preview")
async def upload_preview(file: UploadFile = File(...)):  # noqa: B008
    contents = await file.read()
    filename = file.filename or ""
    df = _read_batch_dataframe(contents, filename)
    return {
        "filename": filename,
        "row_count": len(df),
        "columns": list(df.columns),
        "preview": df.head(3).fillna("").to_dict(orient="records"),
    }


@router.post("/start", response_model=dict)
async def start_batch(
    file: UploadFile = File(...),  # noqa: B008
    column_map_json: str = Form(...),
    clinical_area: str | None = Form(None),
    target_ontology_column: str | None = Form(None),
    target_ontologies_json: str | None = Form(None),
    # Deprecated compatibility field: planned retrieval is controlled by Settings.retrieval_mode.
    deprecated_use_rag: bool = Form(True, alias="use_rag"),
    auto_accept_threshold: float = Form(0.85),
):
    column_map = json.loads(column_map_json)
    target_ontologies = _parse_target_ontologies_json(target_ontologies_json)
    contents = await file.read()
    filename = file.filename or ""
    df = _read_batch_dataframe(contents, filename)
    target_ontology_column = (
        target_ontology_column.strip() if target_ontology_column else None
    )
    row_target_ontologies = _validate_target_ontology_column(
        df,
        target_ontology_column,
    )

    records = df.fillna("").to_dict(orient="records")
    job_id = start_batch_job(
        records=records,
        column_map=column_map,
        clinical_area=clinical_area,
        target_ontologies=target_ontologies,
        auto_accept_threshold=auto_accept_threshold,
        target_ontology_column=target_ontology_column,
        row_target_ontologies=row_target_ontologies,
    )
    return {"job_id": job_id, "total": len(records)}


@router.get("/status/{job_id}", response_model=BatchMappingResponse)
def get_status(job_id: str):
    job = get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return BatchMappingResponse(
        job_id=job_id,
        total=job["total"],
        completed=job["completed"],
        results=job["results"],
        status=job["status"],
        error=job.get("error"),
    )


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    if not cancel_batch_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = get_batch_job(job_id)
    return {"interrupted": job["status"] == "interrupted" if job else True}


@router.patch("/decision/{job_id}/{row_index}")
def set_decision(job_id: str, row_index: int, body: dict):
    decision = body.get("decision")
    if decision not in ("accepted", "rejected", "pending"):
        raise HTTPException(
            status_code=422, detail="decision must be accepted|rejected|pending"
        )
    if not update_batch_decision(job_id, row_index, decision):
        raise HTTPException(status_code=404, detail="Row not found")
    return {"updated": True}


@router.patch("/promote/{job_id}/{row_index}", response_model=dict)
def promote_alternative(job_id: str, row_index: int, body: dict):
    code = body.get("code")
    ontology = body.get("ontology")
    if not isinstance(code, str) or not code.strip():
        raise HTTPException(status_code=422, detail="code is required")
    if ontology is not None and not isinstance(ontology, str):
        raise HTTPException(status_code=422, detail="ontology must be a string")

    row = promote_batch_alternative(
        job_id,
        row_index,
        code,
        ontology,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Row or alternative not found")
    return {"updated": True, "row": row.model_dump(mode="json")}


@router.get("/export/{job_id}")
def export_results(job_id: str):
    job = get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = [
        {
            "field_name": r.field_name,
            "label": r.label or "",
            "suggested_code": r.suggested_code,
            "suggested_term": r.suggested_term,
            "ontology": r.ontology,
            "confidence": f"{r.confidence:.0%}",
            "decision": r.decision,
        }
        for r in job["results"]
    ]

    buf = io.StringIO()
    fieldnames = (
        list(rows[0].keys())
        if rows
        else [
            "field_name",
            "label",
            "suggested_code",
            "suggested_term",
            "ontology",
            "confidence",
            "decision",
        ]
    )
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="batch_results_{job_id[:8]}.csv"'
        },
    )
