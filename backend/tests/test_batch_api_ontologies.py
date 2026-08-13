import csv
import io

import pandas as pd  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from app.main import app
from app.models.mapping import AlternativeResult, BatchRowResult
from app.services.mapper_service import _batch_jobs

client = TestClient(app)


def _csv_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _csv_upload():
    return {
        "file": (
            "data.csv",
            "field_name,label\nsbp,Systolic blood pressure\n",
            "text/csv",
        )
    }


def _csv_upload_with_target_ontology(content: str | None = None):
    return {
        "file": (
            "data.csv",
            content
            or (
                "field_name,label,target_ontology\n"
                "sbp,Systolic blood pressure,loinc\n"
                "short_stature,Short stature,HPO\n"
                "cystic_fibrosis,Cystic fibrosis,RxNorm\n"
            ),
            "text/csv",
        )
    }


def _tsv_upload(
    content: str | bytes = (
        "field_name\tlabel\tclinical_area\n"
        "sys_bp\tSystolic blood pressure\tmeasurement\n"
        "oxygen_sat\tOxygen saturation\tmeasurement\n"
        "cystic_fibrosis\tCystic fibrosis\tdiagnosis\n"
    ),
    *,
    filename: str = "data.tsv",
    content_type: str = "text/tab-separated-values",
):
    return {
        "file": (
            filename,
            content,
            content_type,
        )
    }


def _xlsx_upload():
    buf = io.BytesIO()
    pd.DataFrame(
        [
            {
                "field_name": "sys_bp",
                "label": "Systolic blood pressure",
                "clinical_area": "measurement",
            }
        ]
    ).to_excel(buf, index=False)
    buf.seek(0)
    return {
        "file": (
            "data.xlsx",
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }


def _form_data(target_ontologies_json_marker):
    data = {
        "column_map_json": '{"field_name":"field_name","label":"label"}',
        "clinical_area": "measurement",
        "auto_accept_threshold": "0.85",
    }
    if target_ontologies_json_marker is not _OMITTED:
        data["target_ontologies_json"] = target_ontologies_json_marker
    return data


class _Omitted:
    pass


_OMITTED = _Omitted()


def test_start_batch_omitted_target_ontologies_json(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data(_OMITTED),
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["target_ontologies"] is None


def test_start_batch_blank_target_ontologies_json(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data(""),
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["target_ontologies"] is None


def test_start_batch_empty_target_ontologies_json_array(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data("[]"),
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["target_ontologies"] is None


def test_start_batch_one_target_ontology(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data('["LOINC"]'),
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["target_ontologies"] == ["LOINC"]


def test_start_batch_accepts_efo_target_ontology(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data('["EFO"]'),
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["target_ontologies"] == ["EFO"]


def test_start_batch_multiple_target_ontologies(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data('["LOINC", " HPO ", "loinc", ""]'),
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["target_ontologies"] == ["LOINC", "HPO"]


def test_start_batch_accepts_per_row_target_ontology_column(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data={
            **_form_data('["HPO", "LOINC"]'),
            "target_ontology_column": "target_ontology",
        },
        files=_csv_upload_with_target_ontology(),
    )

    assert response.status_code == 200
    assert captured["target_ontology_column"] == "target_ontology"
    assert captured["target_ontologies"] == ["HPO", "LOINC"]
    assert captured["row_target_ontologies"] == ["LOINC", "HPO", "RxNorm"]


def test_start_batch_passes_optional_history_session_id(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data={
            **_form_data(_OMITTED),
            "session_id": "session-1",
        },
        files=_csv_upload(),
    )

    assert response.status_code == 200
    assert captured["session_id"] == "session-1"


def test_start_batch_accepts_per_row_efo_target_ontology_column(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data={
            **_form_data(_OMITTED),
            "target_ontology_column": "target_ontology",
        },
        files=_csv_upload_with_target_ontology(
            "field_name,label,target_ontology\n"
            "bmi,Body mass index,efo\n"
            "ad,Alzheimer disease,EFO\n"
        ),
    )

    assert response.status_code == 200
    assert captured["row_target_ontologies"] == ["EFO", "EFO"]


def test_start_batch_missing_target_ontology_column_returns_422(monkeypatch):
    response = client.post(
        "/api/batch/start",
        data={
            **_form_data(_OMITTED),
            "target_ontology_column": "missing_ontology",
        },
        files=_csv_upload_with_target_ontology(),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "The selected target ontology column was not found in the uploaded file."
    )


def test_start_batch_invalid_per_row_target_ontology_values_return_422(monkeypatch):
    response = client.post(
        "/api/batch/start",
        data={
            **_form_data(_OMITTED),
            "target_ontology_column": "target_ontology",
        },
        files=_csv_upload_with_target_ontology(
            "field_name,label,target_ontology\n"
            "sbp,Systolic blood pressure,LOIN\n"
            "short_stature,Short stature,\n"
            "cystic_fibrosis,Cystic fibrosis,custom\n"
        ),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "3 rows have invalid target ontology values:" in detail
    assert 'Row 2: "LOIN"' in detail
    assert "Row 3: blank" in detail
    assert 'Row 4: "custom"' in detail
    assert "Supported ontology identifiers: HPO, MONDO, EFO, NCIT, LOINC" in detail


def test_start_batch_malformed_target_ontologies_json_returns_400(monkeypatch):
    response = client.post(
        "/api/batch/start",
        data=_form_data("["),
        files=_csv_upload(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "target_ontologies_json must be a JSON array of strings"
    )


def test_start_batch_non_array_target_ontologies_json_returns_400(monkeypatch):
    response = client.post(
        "/api/batch/start",
        data=_form_data('"LOINC"'),
        files=_csv_upload(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "target_ontologies_json must be a JSON array of strings"
    )


def test_start_batch_non_string_target_ontology_returns_400(monkeypatch):
    response = client.post(
        "/api/batch/start",
        data=_form_data('["LOINC", 3]'),
        files=_csv_upload(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "target_ontologies_json must be a JSON array of strings"
    )


def test_upload_preview_accepts_valid_tsv():
    response = client.post("/api/batch/upload-preview", files=_tsv_upload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "data.tsv"
    assert payload["row_count"] == 3
    assert payload["columns"] == ["field_name", "label", "clinical_area"]
    assert payload["preview"][0]["field_name"] == "sys_bp"


def test_upload_preview_accepts_uppercase_tsv_extension():
    response = client.post(
        "/api/batch/upload-preview",
        files=_tsv_upload(filename="DATA.TSV"),
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "DATA.TSV"


def test_start_batch_parses_tab_separated_headers_and_rows(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)

    response = client.post(
        "/api/batch/start",
        data=_form_data(_OMITTED),
        files=_tsv_upload(),
    )

    assert response.status_code == 200
    assert captured["records"][0]["field_name"] == "sys_bp"
    assert captured["records"][1]["label"] == "Oxygen saturation"
    assert captured["records"][2]["clinical_area"] == "diagnosis"


def test_start_batch_tsv_blank_cells_use_existing_missing_value_handling(monkeypatch):
    captured = {}

    def fake_start_batch_job(**kwargs):
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr("app.api.batch.start_batch_job", fake_start_batch_job)
    content = "field_name\tlabel\tclinical_area\nsys_bp\t\tmeasurement\n"

    response = client.post(
        "/api/batch/start",
        data=_form_data(_OMITTED),
        files=_tsv_upload(content),
    )

    assert response.status_code == 200
    assert captured["records"] == [
        {
            "field_name": "sys_bp",
            "label": "",
            "clinical_area": "measurement",
        }
    ]


def test_upload_preview_tsv_with_utf8_bom():
    content = "\ufefffield_name\tlabel\nsys_bp\tSystolic blood pressure\n"

    response = client.post("/api/batch/upload-preview", files=_tsv_upload(content))

    assert response.status_code == 200
    assert response.json()["columns"] == ["field_name", "label"]


def test_upload_preview_tsv_with_windows_line_endings():
    content = "field_name\tlabel\r\nsys_bp\tSystolic blood pressure\r\n"

    response = client.post("/api/batch/upload-preview", files=_tsv_upload(content))

    assert response.status_code == 200
    assert response.json()["preview"][0]["label"] == "Systolic blood pressure"


def test_upload_preview_tsv_quoted_field_containing_tab():
    content = 'field_name\tlabel\nsys_bp\t"Systolic\tblood pressure"\n'

    response = client.post("/api/batch/upload-preview", files=_tsv_upload(content))

    assert response.status_code == 200
    assert response.json()["preview"][0]["label"] == "Systolic\tblood pressure"


def test_upload_preview_accepts_tsv_reported_as_text_plain():
    response = client.post(
        "/api/batch/upload-preview",
        files=_tsv_upload(content_type="text/plain"),
    )

    assert response.status_code == 200
    assert response.json()["columns"] == ["field_name", "label", "clinical_area"]


def test_upload_preview_rejects_arbitrary_txt_file():
    response = client.post(
        "/api/batch/upload-preview",
        files={
            "file": (
                "data.txt",
                "field_name\tlabel\nsys_bp\tSystolic blood pressure\n",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unsupported file type. Upload a CSV, TSV, or XLSX file."
    )


def test_upload_preview_malformed_tsv_returns_clean_error():
    response = client.post(
        "/api/batch/upload-preview",
        files=_tsv_upload('field_name\tlabel\n"unterminated\tvalue\n'),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "We could not read this TSV file. Check that it is "
        "tab-separated and includes a header row."
    )


def test_upload_preview_existing_xlsx_support_still_works():
    response = client.post("/api/batch/upload-preview", files=_xlsx_upload())

    assert response.status_code == 200
    assert response.json()["columns"] == ["field_name", "label", "clinical_area"]


def test_cancel_running_batch_marks_interrupted_and_preserves_results():
    job_id = "test-running-cancel"
    _batch_jobs[job_id] = {
        "status": "running",
        "total": 2,
        "completed": 1,
        "results": [
            BatchRowResult(
                row_index=0,
                field_name="sbp",
                suggested_code="LOINC:8480-6",
                suggested_term="Systolic blood pressure",
                ontology="LOINC",
                confidence=0.9,
                logic_type="llm",
            )
        ],
        "cancel_requested": False,
    }

    try:
        response = client.post(f"/api/batch/cancel/{job_id}")

        assert response.status_code == 200
        assert response.json() == {"interrupted": True}

        status_response = client.get(f"/api/batch/status/{job_id}")
        assert status_response.status_code == 200
        payload = status_response.json()
        assert payload["status"] == "interrupted"
        assert payload["completed"] == 1
        assert len(payload["results"]) == 1
        assert payload["results"][0]["field_name"] == "sbp"
        assert _batch_jobs[job_id]["cancel_requested"] is True
    finally:
        _batch_jobs.pop(job_id, None)


def test_cancel_completed_batch_preserves_completed_results():
    job_id = "test-done-cancel"
    _batch_jobs[job_id] = {
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [
            BatchRowResult(
                row_index=0,
                field_name="sbp",
                suggested_code="LOINC:8480-6",
                suggested_term="Systolic blood pressure",
                ontology="LOINC",
                confidence=0.9,
                logic_type="llm",
            )
        ],
        "cancel_requested": False,
    }

    try:
        response = client.post(f"/api/batch/cancel/{job_id}")

        assert response.status_code == 200
        assert response.json() == {"interrupted": False}
        assert _batch_jobs[job_id]["status"] == "done"
        assert len(_batch_jobs[job_id]["results"]) == 1
    finally:
        _batch_jobs.pop(job_id, None)


def test_batch_status_serializes_mapping_details_metadata():
    job_id = "test-details-serialization"
    _batch_jobs[job_id] = {
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [
            BatchRowResult(
                row_index=0,
                field_name="sbp",
                label="Systolic blood pressure",
                suggested_code="LOINC:8480-6",
                suggested_term="Systolic blood pressure",
                ontology="LOINC",
                confidence=0.9,
                logic_type="rag",
                notes="Selected because the label matches systolic blood pressure.",
                configured_provider="ollama",
                configured_model="llama3.2",
                retrieval_mode="public",
                alternatives=[
                    AlternativeResult(
                        code="HP:0000822",
                        term="Hypertension",
                        ontology="HPO",
                        confidence=0.72,
                        source="llm",
                        explanation="Alternative-specific reasoning.",
                    )
                ],
            )
        ],
        "cancel_requested": False,
    }

    try:
        response = client.get(f"/api/batch/status/{job_id}")

        assert response.status_code == 200
        row = response.json()["results"][0]
        assert row["notes"] == (
            "Selected because the label matches systolic blood pressure."
        )
        assert row["configured_provider"] == "ollama"
        assert row["configured_model"] == "llama3.2"
        assert row["retrieval_mode"] == "public"
        assert row["alternatives"][0]["source"] == "llm"
        assert row["alternatives"][0]["explanation"] == (
            "Alternative-specific reasoning."
        )
    finally:
        _batch_jobs.pop(job_id, None)


def test_batch_export_preserves_imported_efo_native_ontology():
    job_id = "test-efo-import-export"
    _batch_jobs[job_id] = {
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [
            BatchRowResult(
                row_index=0,
                field_name="ad",
                label="Alzheimer disease",
                suggested_code="MONDO:0004975",
                suggested_term="Alzheimer disease",
                ontology="MONDO",
                confidence=0.99,
                logic_type="rag",
                decision="accepted",
            )
        ],
        "target_ontologies": ["EFO"],
        "cancel_requested": False,
    }

    try:
        response = client.get(f"/api/batch/export/{job_id}")

        assert response.status_code == 200
        rows = _csv_rows(response.text)
        assert rows[0]["mapped_code"] == "MONDO:0004975"
        assert rows[0]["mapped_term"] == "Alzheimer disease"
        assert rows[0]["mapped_ontology"] == "MONDO"
        assert rows[0]["confidence"] == "99%"
        assert rows[0]["decision"] == "accepted"
    finally:
        _batch_jobs.pop(job_id, None)


def test_promote_alternative_updates_row_and_exported_mapping():
    job_id = "test-promote-alternative"
    _batch_jobs[job_id] = {
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [
            BatchRowResult(
                row_index=2,
                field_name="sbp",
                label="Systolic blood pressure",
                suggested_code="LOINC:8480-6",
                suggested_term="Systolic blood pressure",
                ontology="LOINC",
                confidence=0.91,
                logic_type="rag",
                decision="accepted",
                notes="Primary explanation.",
                configured_provider="ollama",
                configured_model="llama3.2",
                retrieval_mode="public",
                alternatives=[
                    AlternativeResult(
                        code="HP:0000822",
                        term="Hypertension",
                        ontology="HPO",
                        confidence=0.72,
                        source="llm",
                        explanation="Alternative-specific reasoning.",
                    )
                ],
            )
        ],
        "cancel_requested": False,
    }

    try:
        response = client.patch(
            f"/api/batch/promote/{job_id}/2",
            json={"code": "HP:0000822", "ontology": "HPO"},
        )

        assert response.status_code == 200
        row = response.json()["row"]
        assert row["suggested_code"] == "HP:0000822"
        assert row["suggested_term"] == "Hypertension"
        assert row["ontology"] == "HPO"
        assert row["confidence"] == 0.72
        assert row["logic_type"] == "llm"
        assert row["decision"] == "pending"
        assert row["notes"] == "Alternative-specific reasoning."
        assert row["alternatives"][0]["code"] == "LOINC:8480-6"
        assert row["alternatives"][0]["explanation"] == "Primary explanation."

        export_response = client.get(f"/api/batch/export/{job_id}")

        assert export_response.status_code == 200
        rows = _csv_rows(export_response.text)
        assert rows[0]["mapped_code"] == "HP:0000822"
        assert rows[0]["mapped_term"] == "Hypertension"
        assert rows[0]["mapped_ontology"] == "HPO"
        assert rows[0]["confidence"] == "72%"
        assert rows[0]["suggested_explanation"] == "Alternative-specific reasoning."
        assert rows[0]["alternative_1_code"] == "LOINC:8480-6"
        assert rows[0]["alternative_1_explanation"] == "Primary explanation."
        assert rows[0]["decision"] == "pending"
    finally:
        _batch_jobs.pop(job_id, None)


def test_promote_alternative_from_unmapped_primary_does_not_demote_placeholder():
    job_id = "test-promote-from-unmapped"
    _batch_jobs[job_id] = {
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [
            BatchRowResult(
                row_index=0,
                field_name="sbp",
                suggested_code="UNMAPPED",
                suggested_term="UNMAPPED",
                ontology="",
                confidence=0,
                logic_type="llm",
                decision="rejected",
                alternatives=[
                    AlternativeResult(
                        code="HP:0000822",
                        term="Hypertension",
                        ontology="HPO",
                        confidence=0.72,
                    )
                ],
            )
        ],
        "cancel_requested": False,
    }

    try:
        response = client.patch(
            f"/api/batch/promote/{job_id}/0",
            json={"code": "HP:0000822", "ontology": "HPO"},
        )

        assert response.status_code == 200
        row = response.json()["row"]
        assert row["suggested_code"] == "HP:0000822"
        assert row["decision"] == "pending"
        assert row["alternatives"] == []
    finally:
        _batch_jobs.pop(job_id, None)
