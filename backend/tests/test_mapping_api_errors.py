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
def test_planned_pipeline_exceptions_map_to_http_status(monkeypatch, exc, expected_status):
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
