import io
import csv
import json
import logging
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import pandas as pd

from app.models.mapping import BatchMappingResponse
from app.services.mapper_service import (
    cancel_batch_job, get_batch_job, start_batch_job, update_batch_decision,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload-preview")
async def upload_preview(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")
    return {
        "filename": file.filename,
        "row_count": len(df),
        "columns": list(df.columns),
        "preview": df.head(3).fillna("").to_dict(orient="records"),
    }


@router.post("/start", response_model=dict)
async def start_batch(
    file: UploadFile = File(...),
    column_map_json: str = Form(...),
    clinical_area: str = Form(None),
    # Deprecated compatibility field: planned retrieval is controlled by Settings.retrieval_mode.
    deprecated_use_rag: bool = Form(True, alias="use_rag"),
    auto_accept_threshold: float = Form(0.85),
):
    column_map = json.loads(column_map_json)
    contents = await file.read()
    try:
        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    records = df.fillna("").to_dict(orient="records")
    job_id = start_batch_job(
        records=records,
        column_map=column_map,
        clinical_area=clinical_area,
        auto_accept_threshold=auto_accept_threshold,
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
    )


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    if not cancel_batch_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"cancelled": True}


@router.patch("/decision/{job_id}/{row_index}")
def set_decision(job_id: str, row_index: int, body: dict):
    decision = body.get("decision")
    if decision not in ("accepted", "rejected", "pending"):
        raise HTTPException(status_code=422, detail="decision must be accepted|rejected|pending")
    if not update_batch_decision(job_id, row_index, decision):
        raise HTTPException(status_code=404, detail="Row not found")
    return {"updated": True}


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
    fieldnames = list(rows[0].keys()) if rows else ["field_name", "label", "suggested_code", "suggested_term", "ontology", "confidence", "decision"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch_results_{job_id[:8]}.csv"'},
    )
