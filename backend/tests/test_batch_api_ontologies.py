from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _csv_upload():
    return {
        "file": (
            "data.csv",
            "field_name,label\nsbp,Systolic blood pressure\n",
            "text/csv",
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
