import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from llm_ontology_mapper import (
    DisabledMappingError,
    LLMRerankerError,
    LocalRetrievalError,
    MappingResultBuilderError,
    PlannedPipelineError,
    PublicRetrievalError,
    QueryPlanningError,
)

from app.api import mapping as mapping_api
from app.main import app
from app.models.mapping import SingleMappingRequest, SingleMappingResponse


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (PublicRetrievalError("public down"), 503),
        (LocalRetrievalError("sapbert down"), 503),
        (PlannedPipelineError("planned failed"), 500),
        (QueryPlanningError("planning failed"), 500),
        (DisabledMappingError("disabled failed"), 500),
        (LLMRerankerError("rerank failed"), 500),
        (MappingResultBuilderError("builder failed"), 500),
    ],
)
def test_planned_pipeline_exceptions_map_to_http_status(
    monkeypatch, exc, expected_status
):
    monkeypatch.setattr(
        mapping_api,
        "map_single_term",
        lambda _request: (_ for _ in ()).throw(exc),
    )

    with pytest.raises(HTTPException) as raised:
        mapping_api.map_single(SingleMappingRequest(source_term="x"))

    assert raised.value.status_code == expected_status
    assert raised.value.detail == str(exc)


def test_wrapped_local_retrieval_error_maps_to_503(monkeypatch):
    exc = PlannedPipelineError("local retrieval failed during planned mapping")
    exc.__cause__ = LocalRetrievalError("no local client")
    monkeypatch.setattr(
        mapping_api,
        "map_single_term",
        lambda _request: (_ for _ in ()).throw(exc),
    )

    with pytest.raises(HTTPException) as raised:
        mapping_api.map_single(SingleMappingRequest(source_term="x"))

    assert raised.value.status_code == 503
    assert raised.value.detail == "local retrieval failed during planned mapping"


def test_wrapped_public_retrieval_error_logs_chained_cause(monkeypatch, caplog):
    def raise_chained_error(_request):
        try:
            raise PublicRetrievalError("specific root cause")
        except PublicRetrievalError as exc:
            raise PlannedPipelineError(
                "public retrieval failed during planned mapping"
            ) from exc

    monkeypatch.setattr(mapping_api, "map_single_term", raise_chained_error)
    caplog.set_level(logging.ERROR, logger=mapping_api.__name__)

    with pytest.raises(HTTPException) as raised:
        mapping_api.map_single(SingleMappingRequest(source_term="x"))

    assert raised.value.status_code == 503
    assert raised.value.detail == "public retrieval failed during planned mapping"
    assert "public retrieval failed during planned mapping" in caplog.text
    assert "specific root cause" in caplog.text


def test_map_single_route_accepts_and_forwards_source_description(monkeypatch):
    captured: dict[str, SingleMappingRequest] = {}

    def fake_map_single_term(request: SingleMappingRequest):
        captured["request"] = request
        return SingleMappingResponse(
            source_term=request.source_term,
            source_label=request.source_label,
            source_type=request.source_type,
            target_code="LOINC:8480-6",
            target_term="Systolic blood pressure",
            ontology="LOINC",
            confidence=0.9,
            logic_type="rag",
            notes="Mapped.",
            alternatives=[],
            configured_provider="ollama",
            configured_model="llama3.2",
            retrieval_mode="public",
        )

    monkeypatch.setattr(mapping_api, "map_single_term", fake_map_single_term)

    client = TestClient(app)
    response = client.post(
        "/api/map/single",
        json={
            "source_term": "sbp",
            "source_label": "Systolic blood pressure",
            "source_description": "Baseline systolic blood pressure measured in mmHg",
        },
    )

    assert response.status_code == 200
    assert captured["request"].source_description == (
        "Baseline systolic blood pressure measured in mmHg"
    )
