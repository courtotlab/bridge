from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.config import AppConfig
from app.models.mapping import SingleMappingRequest
from app.services import mapper_service


def _result(
    *,
    code: str = "HP:0001250",
    term: str = "Seizure",
    ontology: str = "HPO",
    confidence: float = 0.91,
):
    return SimpleNamespace(
        target_code=code,
        target_term=term,
        ontology=ontology,
        confidence=confidence,
        logic_type="rag",
        notes="Mapped.",
        alternatives=[],
        metadata=None,
    )


def _patch_config(monkeypatch, config: AppConfig):
    monkeypatch.setattr(mapper_service, "_validate_config", lambda: None)
    monkeypatch.setattr(mapper_service, "load_config", lambda: config)
    monkeypatch.setattr(mapper_service, "get_sensitive", lambda _field: None)


@pytest.mark.parametrize("mode", ["public", "disabled"])
def test_single_mapping_constructs_planned_mapper_for_public_and_disabled(monkeypatch, mode):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode=mode)
    _patch_config(monkeypatch, config)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", entity_type="phenotype")
    )

    kwargs = mapper_cls.call_args.kwargs
    assert kwargs["use_planned_pipeline"] is True
    assert kwargs["retrieval_mode"] == mode
    assert kwargs["rag_top_k"] == 5
    assert kwargs["max_candidates"] == 10
    assert kwargs["max_alternatives"] == 5
    assert "planned_pipeline" not in kwargs
    assert "ontology_retriever" not in kwargs
    assert "use_rag" not in kwargs
    assert response.target_code == "HP:0001250"
    mapper_instance.map_term.assert_called_once_with(
        source_term="seizure",
        source_label=None,
        source_type=None,
        entity_type="phenotype",
    )


def test_single_mapping_local_injects_planned_pipeline_with_sapbert_url(monkeypatch):
    config = AppConfig(
        provider="ollama",
        model="llama3.2",
        retrieval_mode="local",
        sapbert_server_url="http://localhost:8765",
    )
    _patch_config(monkeypatch, config)

    provider = object()
    local_retriever = object()
    planned_pipeline = object()
    factory = MagicMock()
    factory.from_config.return_value = provider
    local_retriever_cls = MagicMock(return_value=local_retriever)
    planned_pipeline_cls = MagicMock(return_value=planned_pipeline)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)

    monkeypatch.setattr("llm_ontology_mapper.LLMProviderFactory", factory)
    monkeypatch.setattr("llm_ontology_mapper.LocalSemanticRetriever", local_retriever_cls)
    monkeypatch.setattr("llm_ontology_mapper.PlannedPipeline", planned_pipeline_cls)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", entity_type="phenotype")
    )

    factory.from_config.assert_called_once_with(
        provider="ollama",
        model="llama3.2",
        api_key=None,
        base_url="http://localhost:11434",
    )
    local_retriever_cls.assert_called_once_with(sapbert_url="http://localhost:8765")
    planned_pipeline_cls.assert_called_once_with(
        provider=provider,
        local_retriever=local_retriever,
    )
    kwargs = mapper_cls.call_args.kwargs
    assert kwargs["llm_provider"] is provider
    assert kwargs["planned_pipeline"] is planned_pipeline
    assert kwargs["use_planned_pipeline"] is True
    assert kwargs["retrieval_mode"] == "local"
    assert response.target_code == "HP:0001250"


def test_single_mapping_normalizes_planned_unmapped_code(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="UNKNOWN:UNMAPPED",
        term="UNMAPPED",
        ontology="UNKNOWN",
        confidence=0.0,
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="not a clinical term")
    )

    assert response.target_code == "UNMAPPED"
    assert response.target_term == "UNMAPPED"
    assert response.ontology == ""


class _SyncThread:
    def __init__(self, *, target, daemon):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


def test_batch_mapping_runs_with_planned_mapper_and_normalizes_unmapped(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.side_effect = [
        _result(code="LOINC:8480-6", term="Systolic blood pressure", ontology="LOINC"),
        _result(code="UNKNOWN:UNMAPPED", term="UNMAPPED", ontology="UNKNOWN", confidence=0.0),
    ]
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "sbp", "label": "Systolic blood pressure"},
            {"field_name": "x", "label": "No match"},
        ],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area="measurement",
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert job["completed"] == 2
    assert job["results"][0].suggested_code == "LOINC:8480-6"
    assert job["results"][0].decision == "accepted"
    assert job["results"][1].suggested_code == "UNMAPPED"
    assert job["results"][1].suggested_term == "UNMAPPED"
    assert job["results"][1].ontology == ""
    assert job["results"][1].decision == "rejected"
    kwargs = mapper_cls.call_args.kwargs
    assert kwargs["use_planned_pipeline"] is True
    assert "use_rag" not in kwargs
    assert "ontology_retriever" not in kwargs


def test_batch_failed_row_keeps_exception_message(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.side_effect = RuntimeError("planner exploded")
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "x"}],
        column_map={"field_name": "field_name"},
        clinical_area=None,
        auto_accept_threshold=0.85,
    )

    row = mapper_service.get_batch_job(job_id)["results"][0]
    assert row.suggested_code == "UNMAPPED"
    assert row.suggested_term == "planner exploded"
