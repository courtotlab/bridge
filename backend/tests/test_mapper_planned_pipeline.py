import logging
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from llm_ontology_mapper import PlannedPipelineError, PublicRetrievalError

from app.models.config import AppConfig
from app.models.mapping import SingleMappingRequest
from app.services import mapper_service


def _result(
    *,
    code: str = "HP:0001250",
    term: str = "Seizure",
    ontology: str = "HPO",
    confidence: float = 0.91,
    alternatives: list | None = None,
):
    return SimpleNamespace(
        target_code=code,
        target_term=term,
        ontology=ontology,
        confidence=confidence,
        logic_type="rag",
        notes="Mapped.",
        alternatives=alternatives or [],
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
    assert kwargs["rag_top_k"] == 15
    assert kwargs["max_candidates"] == 20
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
        source_description=None,
        strict_target_ontology=False,
    )


def test_single_mapping_does_not_fabricate_missing_alternative_source(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    mapper_instance.map_term.return_value.alternatives = [
        SimpleNamespace(
            code="HP:0000822",
            term="Hypertension",
            ontology="HPO",
            confidence=0.72,
            explanation="Alternative-specific reasoning.",
        )
    ]
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    response = mapper_service.map_single_term(SingleMappingRequest(source_term="sbp"))

    assert response.alternatives[0].source is None
    assert response.alternatives[0].explanation == "Alternative-specific reasoning."


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
        (["EFO"], ["EFO"]),
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


def test_single_mapping_defaults_strict_target_ontology_false(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", target_ontologies=["EFO"])
    )

    assert mapper_instance.map_term.call_args.kwargs["strict_target_ontology"] is False


def test_single_mapping_passes_strict_target_ontology_true_to_mapper(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="EFO:0004340",
        term="body mass index",
        ontology="EFO",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    mapper_service.map_single_term(
        SingleMappingRequest(
            source_term="bmi",
            target_ontologies=["EFO"],
            strict_target_ontology=True,
        )
    )

    assert mapper_instance.map_term.call_args.kwargs["strict_target_ontology"] is True


def test_single_mapping_passes_source_description_to_mapper(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    mapper_service.map_single_term(
        SingleMappingRequest(
            source_term="sbp",
            source_label="Systolic blood pressure",
            source_description="Baseline systolic blood pressure measured in mmHg",
            entity_type="phenotype",
        )
    )

    assert mapper_instance.map_term.call_args.kwargs["source_description"] == (
        "Baseline systolic blood pressure measured in mmHg"
    )


def test_single_mapping_preserves_imported_efo_native_ontology(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="MONDO:0004975",
        term="Alzheimer disease",
        ontology="MONDO",
        confidence=0.99,
    )
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)

    response = mapper_service.map_single_term(
        SingleMappingRequest(
            source_term="alzheimer",
            source_label="Alzheimer disease",
            target_ontologies=["EFO"],
        )
    )

    assert mapper_cls.call_args.kwargs["ontologies"] == ["EFO"]
    assert response.target_code == "MONDO:0004975"
    assert response.target_term == "Alzheimer disease"
    assert response.ontology == "MONDO"
    assert response.confidence == 0.99


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


def test_planned_limit_kwargs_match_public_smoke_test_budgets():
    """Bridge's standard candidate budget must match the llm-ontology-mapper
    public smoke-test configuration: rag_top_k=15, max_candidates=20,
    max_alternatives=5."""
    config = AppConfig(provider="ollama", model="llama3.2")
    kwargs = mapper_service._planned_limit_kwargs(config)
    assert kwargs == {
        "rag_top_k": 15,
        "max_candidates": 20,
        "max_alternatives": 5,
    }


def test_public_retriever_does_not_truncate_candidates_before_reranker(monkeypatch):
    """Bridge must not independently slice the retriever's candidate list
    (e.g. down to 5 or 10) before it reaches the mapper's reranker - the
    mapper itself is solely responsible for applying max_candidates."""
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    deps = _patch_planned_dependencies(monkeypatch)

    fifteen_candidates = [{"code": f"HP:{i:07d}", "rank": i} for i in range(1, 16)]
    deps.public_retriever_cls._call_route = lambda self, query, ontology, top_k: (
        fifteen_candidates
    )

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    mapper_service.map_single_term(SingleMappingRequest(source_term="sbp"))
    retriever = deps.public_retriever_cls.calls[0]["instance"]

    candidates = retriever._call_route("systolic blood pressure", "HPO", 15)

    assert len(candidates) == 15
    # Positions 11-15 (indices 10-14) must survive - no Bridge-level slice to
    # 5 or 10 candidates before the reranker sees them.
    assert candidates[10:15] == fifteen_candidates[10:15]


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
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("loinc-user", "loinc-secret"),
    )
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
    assert kwargs["rag_top_k"] == 15
    assert kwargs["max_candidates"] == 20
    assert kwargs["max_alternatives"] == 5
    assert "planned_pipeline" in kwargs
    assert "use_rag" not in kwargs
    assert "ontology_retriever" not in kwargs
    assert mapper_instance.map_term.call_count == 2


def test_batch_mapping_preserves_original_row_and_passes_source_description(monkeypatch):
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
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[
            {
                "source_variable": "dup",
                "source_label": "Systolic BP",
                "source_description": "Measured seated after five minutes.",
                "target_ontology": "loinc",
                "custom metadata": "alpha",
            },
            {
                "source_variable": "dup",
                "source_label": "Systolic BP",
                "source_description": "Measured standing.",
                "target_ontology": "loinc",
                "custom metadata": "beta",
            },
        ],
        column_map={
            "field_name": "source_variable",
            "label": "source_label",
            "description": "source_description",
        },
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
        target_ontology_column="target_ontology",
        row_target_ontologies=["LOINC", "LOINC"],
        original_columns=[
            "source_variable",
            "source_label",
            "source_description",
            "target_ontology",
            "custom metadata",
        ],
    )

    job = mapper_service.get_batch_job(job_id)
    rows = job["results"]

    assert rows[0].original_row["custom metadata"] == "alpha"
    assert rows[1].original_row["custom metadata"] == "beta"
    assert rows[0].original_columns == [
        "source_variable",
        "source_label",
        "source_description",
        "target_ontology",
        "custom metadata",
    ]
    assert rows[0].source_description == "Measured seated after five minutes."
    assert rows[0].requested_target_ontology == "LOINC"
    assert mapper_instance.map_term.call_args_list[0].kwargs["source_description"] == (
        "Measured seated after five minutes."
    )
    assert mapper_instance.map_term.call_args_list[1].kwargs["source_description"] == (
        "Measured standing."
    )


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


def test_batch_planned_pipeline_error_logs_chained_cause(monkeypatch, caplog):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    def raise_chained_error(*_args, **_kwargs):
        try:
            raise PublicRetrievalError("specific root cause")
        except PublicRetrievalError as exc:
            raise PlannedPipelineError(
                "public retrieval failed during planned mapping"
            ) from exc

    mapper_instance = MagicMock()
    mapper_instance.map_term.side_effect = raise_chained_error
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)
    caplog.set_level(logging.ERROR, logger=mapper_service.__name__)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "x"}],
        column_map={"field_name": "field_name"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
    )

    row = mapper_service.get_batch_job(job_id)["results"][0]
    assert row.suggested_code == "UNMAPPED"
    assert row.suggested_term == "public retrieval failed during planned mapping"
    assert "public retrieval failed during planned mapping" in caplog.text
    assert "specific root cause" in caplog.text


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


def test_batch_mapping_uses_per_row_target_ontology_over_global_selection(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    monkeypatch.setattr(
        mapper_service,
        "get_validated_loinc_credentials",
        lambda _config: ("loinc-user", "loinc-secret"),
    )
    mapper_service._batch_jobs.clear()

    mapper_instances = {}

    def mapper_factory(**kwargs):
        ontologies = tuple(kwargs["ontologies"] or [])
        mapper = MagicMock()
        if ontologies == ("LOINC",):
            mapper.map_term.return_value = _result(
                code="LOINC:8480-6",
                term="Systolic blood pressure",
                ontology="LOINC",
            )
        elif ontologies == ("HPO",):
            mapper.map_term.return_value = _result(
                code="HP:0004322",
                term="Short stature",
                ontology="HPO",
            )
        else:
            mapper.map_term.return_value = _result(
                code="MONDO:0000001",
                term="Disease",
                ontology="MONDO",
            )
        mapper_instances[ontologies] = mapper
        return mapper

    mapper_cls = MagicMock(side_effect=mapper_factory)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "sbp", "label": "Systolic blood pressure"},
            {"field_name": "short_stature", "label": "Short stature"},
            {"field_name": "sbp_2", "label": "Systolic blood pressure"},
        ],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["MONDO"],
        auto_accept_threshold=0.85,
        target_ontology_column="target_ontology",
        row_target_ontologies=["LOINC", "HPO", "LOINC"],
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert job["target_ontologies"] == ["MONDO"]
    assert job["target_ontology_column"] == "target_ontology"
    assert [row.ontology for row in job["results"]] == ["LOINC", "HPO", "LOINC"]
    assert [call.kwargs["ontologies"] for call in mapper_cls.call_args_list] == [
        ["LOINC"],
        ["HPO"],
    ]
    assert mapper_instances[("LOINC",)].map_term.call_count == 2
    assert mapper_instances[("HPO",)].map_term.call_count == 1


def test_batch_mapping_preserves_imported_efo_native_ontology(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="MONDO:0004975",
        term="Alzheimer disease",
        ontology="MONDO",
        confidence=0.99,
    )
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "ad", "label": "Alzheimer disease"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["EFO"],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    row = job["results"][0]
    assert job["status"] == "done"
    assert job["target_ontologies"] == ["EFO"]
    assert mapper_cls.call_args.kwargs["ontologies"] == ["EFO"]
    assert row.suggested_code == "MONDO:0004975"
    assert row.suggested_term == "Alzheimer disease"
    assert row.ontology == "MONDO"
    assert row.confidence == 0.99
    assert row.decision == "accepted"


def test_batch_mapping_preserves_efo_alternatives_from_imported_ontologies(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="EFO:0004340",
        term="body mass index",
        ontology="EFO",
        alternatives=[
            SimpleNamespace(
                code="MONDO:0004975",
                term="Alzheimer disease",
                ontology="MONDO",
                confidence=0.87,
                source="rag",
                explanation="EFO imported candidate.",
            )
        ],
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "bmi", "label": "Body mass index"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["EFO"],
        auto_accept_threshold=0.85,
    )

    row = mapper_service.get_batch_job(job_id)["results"][0]
    assert [(alt.code, alt.term, alt.ontology) for alt in row.alternatives] == [
        ("MONDO:0004975", "Alzheimer disease", "MONDO")
    ]


def test_batch_mapping_uses_per_row_efo_target_ontology(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="EFO:0004340",
        term="body mass index",
        ontology="EFO",
    )
    mapper_cls = MagicMock(return_value=mapper_instance)
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "bmi", "label": "Body mass index"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["MONDO"],
        auto_accept_threshold=0.85,
        target_ontology_column="target_ontology",
        row_target_ontologies=["EFO"],
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["results"][0].ontology == "EFO"
    assert mapper_cls.call_args.kwargs["ontologies"] == ["EFO"]


def test_batch_mapping_converts_wrong_ontology_result_to_unmapped(monkeypatch):
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
    mapper_instance.map_term.return_value = _result(
        code="HP:0001250",
        term="Seizure",
        ontology="HPO",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "sbp", "label": "Systolic blood pressure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["HPO"],
        auto_accept_threshold=0.85,
        target_ontology_column="target_ontology",
        row_target_ontologies=["LOINC"],
    )

    row = mapper_service.get_batch_job(job_id)["results"][0]
    assert row.suggested_code == "UNMAPPED"
    assert row.suggested_term == "UNMAPPED"
    assert row.ontology == ""
    assert row.decision == "rejected"


def test_batch_mapping_defaults_strict_target_ontology_false(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result()
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "sbp", "label": "Systolic blood pressure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["EFO"],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert (
        mapper_instance.map_term.call_args.kwargs["strict_target_ontology"] is False
    )


def test_batch_mapping_passes_strict_target_ontology_to_every_row(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="EFO:0004340",
        term="body mass index",
        ontology="EFO",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "bmi", "label": "Body mass index"},
            {"field_name": "ad", "label": "Alzheimer disease"},
            {"field_name": "height", "label": "Height"},
        ],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["EFO"],
        auto_accept_threshold=0.85,
        strict_target_ontology=True,
    )

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert mapper_instance.map_term.call_count == 3
    assert all(
        call.kwargs["strict_target_ontology"] is True
        for call in mapper_instance.map_term.call_args_list
    )


# ── Ontology entity URL enrichment ───────────────────────────────────────────


def test_single_mapping_response_includes_target_url(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
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

    response = mapper_service.map_single_term(SingleMappingRequest(source_term="sbp"))

    assert response.target_url == "https://loinc.org/8480-6"


def test_single_mapping_alternative_has_its_own_url(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:76534-7",
        term="Diastolic blood pressure",
        ontology="LOINC",
        alternatives=[
            SimpleNamespace(
                code="LOINC:76215-3",
                term="Systolic blood pressure alt",
                ontology="LOINC",
                confidence=0.6,
                source="rag",
                explanation=None,
            )
        ],
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    response = mapper_service.map_single_term(SingleMappingRequest(source_term="dbp"))

    assert response.target_url == "https://loinc.org/76534-7"
    assert response.alternatives[0].url == "https://loinc.org/76215-3"
    # Each alternative resolves independently from its own code, not the
    # primary result's code.
    assert response.alternatives[0].url != response.target_url


def test_single_mapping_url_follows_returned_code_not_requested_ontology(monkeypatch):
    # Requested ontology is EFO, but the mapper returns an HPO code — the
    # entity link must point at HPO, never at EFO.
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="HP:0001250",
        term="Seizure",
        ontology="HPO",
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )

    response = mapper_service.map_single_term(
        SingleMappingRequest(source_term="seizure", target_ontologies=["EFO"])
    )

    assert response.target_url is not None
    assert "ontologies/hp/" in response.target_url
    assert "ontologies/efo/" not in response.target_url


def test_single_mapping_unmapped_has_no_url(monkeypatch):
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

    response = mapper_service.map_single_term(SingleMappingRequest(source_term="???"))

    assert response.target_code == "UNMAPPED"
    assert response.target_url is None


def test_single_mapping_url_identical_across_public_and_local_mode(monkeypatch):
    urls = {}
    for mode in ("public", "local"):
        config = AppConfig(
            provider="ollama",
            model="llama3.2",
            retrieval_mode=mode,
            sapbert_server_url="http://localhost:8765",
        )
        _patch_config(monkeypatch, config)
        _patch_planned_dependencies(monkeypatch)
        monkeypatch.setattr(
            "llm_ontology_mapper.LocalSemanticRetriever",
            MagicMock(return_value=object()),
        )

        mapper_instance = MagicMock()
        mapper_instance.map_term.return_value = _result(
            code="SNOMEDCT:138875005",
            term="Substance",
            ontology="SNOMED-CT",
        )
        monkeypatch.setattr(
            "llm_ontology_mapper.OntologyMapper",
            MagicMock(return_value=mapper_instance),
        )

        response = mapper_service.map_single_term(SingleMappingRequest(source_term="substance"))
        urls[mode] = response.target_url

    assert urls["public"] is not None
    assert urls["public"] == urls["local"]


def test_batch_mapping_row_includes_suggested_url(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

    mapper_instance = MagicMock()
    mapper_instance.map_term.return_value = _result(
        code="LOINC:8480-6",
        term="Systolic blood pressure",
        ontology="LOINC",
        alternatives=[
            SimpleNamespace(
                code="LOINC:76534-7",
                term="Diastolic blood pressure",
                ontology="LOINC",
                confidence=0.6,
                source="rag",
                explanation=None,
            )
        ],
    )
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "sbp", "label": "Systolic blood pressure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    row = job["results"][0]
    assert row.suggested_url == "https://loinc.org/8480-6"
    assert row.alternatives[0].url == "https://loinc.org/76534-7"


def test_batch_mapping_url_follows_returned_code_not_requested_ontology(monkeypatch):
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
    monkeypatch.setattr(
        "llm_ontology_mapper.OntologyMapper",
        MagicMock(return_value=mapper_instance),
    )
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "seizure", "label": "Seizure"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=["EFO"],
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    row = job["results"][0]
    assert row.suggested_code == "HP:0001250"
    assert row.suggested_url is not None
    assert "ontologies/hp/" in row.suggested_url


def test_batch_mapping_unmapped_row_has_no_url(monkeypatch):
    config = AppConfig(provider="ollama", model="llama3.2", retrieval_mode="public")
    _patch_config(monkeypatch, config)
    _patch_planned_dependencies(monkeypatch)
    mapper_service._batch_jobs.clear()

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
    monkeypatch.setattr("threading.Thread", _SyncThread)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "gibberish", "label": "asdkfjh"}],
        column_map={"field_name": "field_name", "label": "label"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
    )

    job = mapper_service.get_batch_job(job_id)
    row = job["results"][0]
    assert row.suggested_code == "UNMAPPED"
    assert row.suggested_url is None
