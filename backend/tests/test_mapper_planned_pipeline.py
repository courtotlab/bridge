from types import SimpleNamespace
from typing import ClassVar
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
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: None,
    )


def _patch_planned_dependencies(monkeypatch):
    provider = object()
    search_tools = MagicMock()
    planned_pipeline = object()

    factory = MagicMock()
    factory.from_config.return_value = provider
    search_tools_cls = MagicMock(return_value=search_tools)
    planned_pipeline_cls = MagicMock(return_value=planned_pipeline)

    class FakePublicOntologyRetriever:
        calls: ClassVar[list[dict]] = []

        def __init__(self, search_tools=None):
            self.search_tools = search_tools
            self.calls.append({"search_tools": search_tools, "instance": self})

        def _call_route(self, query: str, ontology: str, top_k: int):
            return []

    FakePublicOntologyRetriever.calls = []

    monkeypatch.setattr("llm_ontology_mapper.LLMProviderFactory", factory)
    monkeypatch.setattr("llm_ontology_mapper.search_tools.SearchTools", search_tools_cls)
    monkeypatch.setattr(
        "llm_ontology_mapper.PublicOntologyRetriever",
        FakePublicOntologyRetriever,
    )
    monkeypatch.setattr("llm_ontology_mapper.PlannedPipeline", planned_pipeline_cls)

    return SimpleNamespace(
        provider=provider,
        search_tools=search_tools,
        public_retriever_cls=FakePublicOntologyRetriever,
        planned_pipeline=planned_pipeline,
        factory=factory,
        search_tools_cls=search_tools_cls,
        planned_pipeline_cls=planned_pipeline_cls,
    )


@pytest.mark.parametrize("mode", ["public", "disabled"])
def test_single_mapping_constructs_planned_mapper_for_public_and_disabled(
    monkeypatch, mode
):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode=mode)
    _patch_config(monkeypatch, config)
    deps = _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", entity_type="phenotype")
    )

    kwargs = mapper_cls.call_args.kwargs
    assert kwargs["ontologies"] is None
    assert kwargs["use_planned_pipeline"] is True
    assert kwargs["retrieval_mode"] == mode
    assert kwargs["rag_top_k"] == 5
    assert kwargs["max_candidates"] == 10
    assert kwargs["max_alternatives"] == 5
    assert kwargs["llm_provider"] is deps.provider
    assert kwargs["planned_pipeline"] is deps.planned_pipeline
    assert "ontology_retriever" not in kwargs
    assert "use_rag" not in kwargs
    deps.search_tools_cls.assert_called_once_with(
        loinc_username="",
        loinc_password="",
    )
    deps.planned_pipeline_cls.assert_called_once_with(
        provider=deps.provider,
        public_retriever=deps.public_retriever_cls.calls[0]["instance"],
        local_retriever=None,
    )
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

    deps = _patch_planned_dependencies(monkeypatch)
    local_retriever = object()
    local_retriever_cls = MagicMock(return_value=local_retriever)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)

    monkeypatch.setattr(
        "llm_ontology_mapper.LocalSemanticRetriever", local_retriever_cls
    )
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", entity_type="phenotype")
    )

    deps.factory.from_config.assert_called_once_with(
        provider="ollama",
        model="llama3.2",
        api_key=None,
        base_url="http://localhost:11434",
    )
    local_retriever_cls.assert_called_once_with(sapbert_url="http://localhost:8765")
    deps.planned_pipeline_cls.assert_called_once_with(
        provider=deps.provider,
        public_retriever=deps.public_retriever_cls.calls[0]["instance"],
        local_retriever=local_retriever,
    )
    kwargs = mapper_cls.call_args.kwargs
    assert kwargs["ontologies"] is None
    assert kwargs["llm_provider"] is deps.provider
    assert kwargs["planned_pipeline"] is deps.planned_pipeline
    assert kwargs["use_planned_pipeline"] is True
    assert kwargs["retrieval_mode"] == "local"
    assert response.target_code == "HP:0001250"


def test_local_loinc_mapping_does_not_require_public_loinc_credentials(monkeypatch):
    config = AppConfig(
        provider="ollama",
        model="llama3.2",
        retrieval_mode="local",
        sapbert_server_url="http://localhost:8765",
    )
    _patch_config(monkeypatch, config)
    deps = _patch_planned_dependencies(monkeypatch)
    local_retriever_cls = MagicMock(return_value=object())

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    mapper_cls = MagicMock(return_value=mapper_instance)

    monkeypatch.setattr(
        "llm_ontology_mapper.LocalSemanticRetriever",
        local_retriever_cls,
    )
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
    )

    assert response.target_code == "LOINC:8480-6"
    assert mapper_cls.call_args.kwargs["ontologies"] == ["LOINC"]
    deps.search_tools_cls.assert_called_once_with(
        loinc_username="",
        loinc_password="",
    )


def test_single_mapping_normalizes_planned_unmapped_code(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

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


@pytest.mark.parametrize(
    ("target_ontologies", "expected"),
    [
        (None, None),
        (["LOINC"], ["LOINC"]),
        (["LOINC", "HPO"], ["LOINC", "HPO"]),
    ],
)
def test_single_mapping_passes_target_ontologies_to_mapper(
    monkeypatch, target_ontologies, expected
):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    if expected and "LOINC" in expected:
        monkeypatch.setattr(
            mapper_service,
            "get_validated_loinc_credentials",
            lambda _config: ("loinc-user", "loinc-secret"),
        )

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    mapper_service.map_single_term(
        SingleMappingRequest(
            source_term="seizure",
            entity_type="phenotype",
            target_ontologies=target_ontologies,
        )
    )

    assert mapper_cls.call_args.kwargs["ontologies"] == expected


def test_single_public_loinc_mapping_uses_validated_user_credentials(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("bridge-user", "bridge-secret"),
    )
    deps = _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    mapper_service.map_single_term(
        SingleMappingRequest(
            source_term="sbp",
            source_label="Systolic blood pressure",
            target_ontologies=["LOINC"],
        )
    )

    deps.search_tools_cls.assert_called_once_with(
        loinc_username="bridge-user",
        loinc_password="bridge-secret",
    )
    assert mapper_cls.call_args.kwargs["ontologies"] == ["LOINC"]


def test_validated_loinc_credentials_override_environment_credentials(
    monkeypatch,
):
    monkeypatch.setenv("LOINC_USERNAME", "env-user")
    monkeypatch.setenv("LOINC_PASSWORD", "env-secret")
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("bridge-user", "bridge-secret"),
    )
    deps = _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    mapper_service.map_single_term(
        SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
    )

    deps.search_tools_cls.assert_called_once_with(
        loinc_username="bridge-user",
        loinc_password="bridge-secret",
    )


def test_unvalidated_public_non_loinc_mapping_does_not_fall_back_to_environment(
    monkeypatch,
):
    monkeypatch.setenv("LOINC_USERNAME", "env-user")
    monkeypatch.setenv("LOINC_PASSWORD", "env-secret")
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    deps = _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", target_ontologies=["HPO"])
    )

    assert response.target_code == "HP:0001250"
    deps.search_tools_cls.assert_called_once_with(
        loinc_username="",
        loinc_password="",
    )


def test_unvalidated_public_loinc_mapping_fails_without_environment_fallback(
    monkeypatch,
):
    monkeypatch.setenv("LOINC_USERNAME", "env-user")
    monkeypatch.setenv("LOINC_PASSWORD", "env-secret")
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    with pytest.raises(ValueError, match="LOINC credentials must be validated"):
        mapper_service.map_single_term(
            SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
        )


def test_failed_public_loinc_validation_does_not_allow_mapping(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: None,
    )
    _patch_planned_dependencies(monkeypatch)

    with pytest.raises(ValueError, match="LOINC credentials must be validated"):
        mapper_service.map_single_term(
            SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
        )


def test_mixed_public_ontologies_skip_unavailable_loinc_with_warning(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", target_ontologies=["LOINC", "HPO"])
    )

    assert mapper_cls.call_args.kwargs["ontologies"] == ["HPO"]
    assert response.target_code == "HP:0001250"
    assert "LOINC retrieval was skipped" in response.notes


def test_public_retriever_blocks_implicit_loinc_without_validated_credentials(
    monkeypatch,
):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    deps = _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    mapper_service.map_single_term(SingleMappingRequest(source_term="sbp"))
    retriever = deps.public_retriever_cls.calls[0]["instance"]

    with pytest.raises(Exception, match="LOINC credentials must be validated"):
        retriever._call_route("glucose", "LOINC", 1)


def test_changed_credentials_stop_public_loinc_mapping(monkeypatch):
    config = AppConfig(
        provider="ollama",
        model="llama3.2",
        retrieval_mode="public",
        loinc_username="changed-user",
    )
    _patch_config(monkeypatch, config)

    def credentials(current_config):
        if current_config.loinc_username == "validated-user":
            return "validated-user", "validated-secret"
        return None

    monkeypatch.setattr(mapper_service, "get_validated_loinc_credentials", credentials)
    _patch_planned_dependencies(monkeypatch)

    with pytest.raises(ValueError, match="LOINC credentials must be validated"):
        mapper_service.map_single_term(
            SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
        )


def test_memory_reset_stops_public_loinc_mapping(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: None,
    )
    _patch_planned_dependencies(monkeypatch)

    with pytest.raises(ValueError, match="LOINC credentials must be validated"):
        mapper_service.map_single_term(
            SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
        )


def test_masked_sentinel_is_never_passed_to_search_tools(monkeypatch):
    config = AppConfig(
        provider="ollama",
        model="llama3.2",
        retrieval_mode="public",
        loinc_username="loinc-user",
        loinc_password="••••••••",
    )
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("loinc-user", "memory-secret"),
    )
    deps = _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    mapper_service.map_single_term(
        SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
    )

    deps.search_tools_cls.assert_called_once_with(
        loinc_username="loinc-user",
        loinc_password="memory-secret",
    )


def test_loinc_password_is_not_logged_or_returned(monkeypatch, capsys, caplog):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("loinc-user", "bridge-secret"),
    )
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC"])
    )

    captured = capsys.readouterr()
    combined_logs = captured.out + captured.err + caplog.text + response.model_dump_json()
    assert "bridge-secret" not in combined_logs


class _SyncThread:
    def __init__(self, *, target, daemon):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


def test_batch_mapping_runs_with_planned_mapper_and_normalizes_unmapped(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.side_effect = [
        _result(code="LOINC:8480-6", term="Systolic blood pressure", ontology="LOINC"),
        _result(
            code="UNKNOWN:UNMAPPED", term="UNMAPPED", ontology="UNKNOWN", confidence=0.0
        ),
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
        target_ontologies=None,
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
    assert job["target_ontologies"] is None
    assert mapper_cls.call_count == 1
    kwargs = mapper_cls.call_args.kwargs
    assert kwargs["ontologies"] is None
    assert kwargs["use_planned_pipeline"] is True
    assert "planned_pipeline" in kwargs
    assert "use_rag" not in kwargs
    assert "ontology_retriever" not in kwargs
    assert mapper_instance.map_term.call_count == 2


def test_batch_public_loinc_mapping_uses_validated_user_credentials(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("bridge-user", "bridge-secret"),
    )
    deps = _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "sbp", "label": "Systolic blood pressure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area="measurement",
        target_ontologies=["LOINC"],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert job["results"][0].suggested_code == "LOINC:8480-6"
    deps.search_tools_cls.assert_called_once_with(
        loinc_username="bridge-user",
        loinc_password="bridge-secret",
    )
    assert mapper_cls.call_args.kwargs["ontologies"] == ["LOINC"]


def test_batch_public_loinc_without_validation_fails_safely(monkeypatch):
    monkeypatch.setenv("LOINC_USERNAME", "env-user")
    monkeypatch.setenv("LOINC_PASSWORD", "env-secret")
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "sbp", "label": "Systolic blood pressure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area="measurement",
        target_ontologies=["LOINC"],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == mapper_service._LOINC_CREDENTIALS_REQUIRED_MESSAGE


def test_batch_mixed_public_ontologies_skip_unavailable_loinc_with_warning(
    monkeypatch,
):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="HP:0001250",
        term="Seizure",
        ontology="HPO",
    )
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "seizure", "label": "Seizure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area="phenotype",
        target_ontologies=["LOINC", "HPO"],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert mapper_cls.call_args.kwargs["ontologies"] == ["HPO"]
    assert job["results"][0].suggested_code == "HP:0001250"
    assert "LOINC retrieval was skipped" in job["results"][0].notes


def test_batch_failed_row_keeps_exception_message(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
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
        target_ontologies=None,
        auto_accept_threshold=0.85,
    )

    row = mapper_service.get_batch_job(job_id)["results"][0]
    assert row.suggested_code == "UNMAPPED"
    assert row.suggested_term == "planner exploded"


def test_batch_mapping_reuses_one_mapper_with_normalized_target_ontologies(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("loinc-user", "loinc-secret"),
    )
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.side_effect = [
        _result(code="LOINC:8480-6", term="Systolic blood pressure", ontology="LOINC"),
        _result(code="HP:0001250", term="Seizure", ontology="HPO"),
    ]
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "sbp", "label": "Systolic blood pressure"},
            {"field_name": "seizure", "label": "Seizure"},
        ],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area="measurement",
        target_ontologies=["LOINC", " HPO ", "loinc", ""],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert job["target_ontologies"] == ["LOINC", "HPO"]
    assert mapper_cls.call_count == 1
    assert mapper_cls.call_args.kwargs["ontologies"] == ["LOINC", "HPO"]
    assert mapper_instance.map_term.call_count == 2
