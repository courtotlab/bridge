import logging

import pytest
from fastapi import HTTPException
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
from app.models.mapping import SingleMappingRequest


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
