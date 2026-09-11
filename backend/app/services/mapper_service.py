import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.mapping import (
    AlternativeResult,
    BatchMappingResponse,
    MappingMetadata,
    SingleMappingRequest,
    SingleMappingResponse,
)
from app.storage.config_store import (
    get_sensitive,
    get_validated_loinc_credentials,
    load_config,
)
from app.storage.session_store import complete_session
from app.utils.ontology import normalize_target_ontologies
from app.utils.ontology_urls import resolve_ontology_url

# ── Batch job store ──────────────────────────────────────────────────────────
_batch_jobs: dict[str, dict] = {}
_batch_jobs_lock = threading.Lock()
_TERMINAL_BATCH_STATUSES = {"done", "failed", "interrupted"}

logger = logging.getLogger(__name__)

_CLOUD_PROVIDERS = {"openai", "anthropic", "ollama_cloud"}
_OLLAMA_PROVIDERS = {"ollama", "ollama_cloud"}
_OLLAMA_CLOUD_BASE = "https://ollama.com"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
_PLANNED_RAG_TOP_K = 15
_PLANNED_MAX_CANDIDATES = 20
_PLANNED_MAX_ALTERNATIVES = 5
_LOINC_CREDENTIALS_REQUIRED_MESSAGE = (
    "LOINC credentials must be validated in Settings before running public LOINC retrieval."
)
_LOINC_OMITTED_WARNING = (
    "LOINC retrieval was skipped because LOINC credentials have not been validated in Settings."
)


def _mark_batch_interrupted_locked(job: dict) -> None:
    """Mark a running batch interrupted without discarding completed results."""
    if job["status"] in {"done", "failed"}:
        return
    job["cancel_requested"] = True
    job["status"] = "interrupted"
    job["completed"] = len(job["results"])
    job["interrupted_at"] = datetime.now(timezone.utc).isoformat()


def _mark_batch_failed_locked(job: dict, error: str) -> None:
    if job["status"] in _TERMINAL_BATCH_STATUSES:
        return
    job["status"] = "failed"
    job["error"] = error
    job["ended_at"] = datetime.now(timezone.utc).isoformat()


def _mark_batch_done_locked(job: dict) -> None:
    if job.get("cancel_requested") or job["status"] == "interrupted":
        _mark_batch_interrupted_locked(job)
        return
    if job["status"] in _TERMINAL_BATCH_STATUSES:
        return
    job["status"] = "done"
    job["ended_at"] = datetime.now(timezone.utc).isoformat()


def _batch_response_snapshot(job_id: str, job: dict) -> dict:
    return BatchMappingResponse(
        job_id=job_id,
        total=job["total"],
        completed=job["completed"],
        results=job["results"],
        status=job["status"],
        error=job.get("error"),
    ).model_dump(mode="json")


def _terminal_history_snapshot_locked(
    job_id: str,
    job: dict,
) -> tuple[str, str, dict] | None:
    session_id = job.get("session_id")
    status = job.get("status")
    if not session_id or status not in _TERMINAL_BATCH_STATUSES:
        return None
    history_status = {
        "done": "complete",
        "failed": "error",
        "interrupted": "interrupted",
    }[status]
    return str(session_id), history_status, _batch_response_snapshot(job_id, job)


def _persist_terminal_batch_history(
    job_id: str,
    history_snapshot: tuple[str, str, dict] | None,
) -> None:
    if history_snapshot is None:
        return
    session_id, history_status, snapshot = history_snapshot
    try:
        complete_session(session_id, history_status, snapshot)
        logger.info(
            "[batch:%s] history session=%s status=%s",
            job_id,
            session_id,
            history_status,
        )
    except KeyError:
        logger.warning(
            "Batch job %s could not persist terminal history snapshot: "
            "session %s was not found",
            job_id,
            session_id,
        )
    except Exception:
        logger.exception(
            "Batch job %s could not persist terminal history snapshot",
            job_id,
        )

# Fix 2: frontend option values (lowercase, "/" → "_") → library entity_type
_CLINICAL_AREA_MAP: dict[str, str | None] = {
    "phenotype_symptom": "phenotype",
    "disease_condition": "disease",
    "lab_measurement": "measurement",
    "medication": "medication",
    "demographic": "demographic",
    "other": "other",
    # pass-through for callers that already use library values
    "phenotype": "phenotype",
    "disease": "disease",
    "measurement": "measurement",
}


def _map_entity_type(clinical_area: str | None) -> str | None:
    if not clinical_area:
        return None
    return _CLINICAL_AREA_MAP.get(clinical_area.lower())


# Fix 5: "ollama_cloud" uses OllamaProvider — just needs base_url/api_key
def _normalise_provider(provider: str) -> str:
    return "ollama" if provider == "ollama_cloud" else provider


def _provider_extra_kwargs(config) -> dict:
    """Build non-secret provider kwargs shared by OntologyMapper and LLMProviderFactory."""
    kwargs: dict = {}
    if config.provider in _OLLAMA_PROVIDERS:
        from urllib.parse import urlparse

        raw = (config.base_url or "").rstrip("/")
        host = urlparse(raw).hostname or "" if raw else ""
        kwargs["base_url"] = (
            _OLLAMA_CLOUD_BASE
            if config.provider == "ollama_cloud" and (not raw or host in _LOCAL_HOSTS)
            else raw or None
        )
    return kwargs


_ONTOLOGY_COMPARE_NORMALIZE: dict[str, str] = {
    "HP": "HPO",
    "HPO": "HPO",
    "MONDO": "MONDO",
    "EFO": "EFO",
    "NCIT": "NCIT",
    "LOINC": "LOINC",
    "ICD10": "ICD10",
    "ICD10CM": "ICD10",
    "CHEBI": "CHEBI",
    "SNOMED": "SNOMED",
    "SNOMEDCT": "SNOMED",
    "SNOMED-CT": "SNOMED",
    "RXNORM": "RXNORM",
}


def _normalize_for_comparison(o: str | None) -> str:
    if not o:
        return ""
    upper = o.upper().strip()
    return _ONTOLOGY_COMPARE_NORMALIZE.get(upper, upper)


def _is_loinc_ontology(ontology: str | None) -> bool:
    return _normalize_for_comparison(ontology) == "LOINC"


def _filter_unavailable_loinc_ontology(
    ontologies: list[str] | None,
    *,
    has_validated_loinc_credentials: bool,
) -> tuple[list[str] | None, str | None]:
    if has_validated_loinc_credentials or not ontologies:
        return ontologies, None
    non_loinc = [ontology for ontology in ontologies if not _is_loinc_ontology(ontology)]
    if len(non_loinc) == len(ontologies):
        return ontologies, None
    if not non_loinc:
        raise ValueError(_LOINC_CREDENTIALS_REQUIRED_MESSAGE)
    return non_loinc, _LOINC_OMITTED_WARNING


def _append_mapping_warning(notes: str | None, warning: str | None) -> str | None:
    if not warning:
        return notes
    if notes:
        return f"{notes} {warning}"
    return warning


def _json_safe_original_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "item"):
        try:
            return _json_safe_original_value(value.item())
        except (AttributeError, TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    return str(value)


def _json_safe_original_row(rec: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe_original_value(value) for key, value in rec.items()}


def _infer_ontology_from_code(code: str) -> str:
    """Derive a canonical ontology label from a CURIE prefix."""
    if not code or ":" not in code:
        return code
    prefix = code.split(":", 1)[0].upper()
    return {
        "HP": "HPO",
        "HPO": "HPO",
        "MONDO": "MONDO",
        "EFO": "EFO",
        "NCIT": "NCIT",
        "LOINC": "LOINC",
        "ICD10": "ICD10",
        "ICD10CM": "ICD10",
        "RXNORM": "RxNorm",
        "RXCUI": "RxNorm",
        "SNOMEDCT": "SNOMED-CT",
        "SNOMED": "SNOMED-CT",
        "CHEBI": "CHEBI",
        "UO": "UO",
    }.get(prefix, prefix)


def _validate_config() -> None:
    config = load_config()
    if not config.provider:
        raise ValueError(
            "No AI provider configured. Please go to Settings and save your "
            "configuration before searching."
        )
    if not config.model:
        raise ValueError(
            "No AI model configured. Please go to Settings and save your "
            "configuration before searching."
        )
    if config.provider in _CLOUD_PROVIDERS and not get_sensitive("api_key"):
        raise ValueError(
            "No API key configured. Please go to Settings and save your "
            "configuration before searching."
        )


def _planned_limit_kwargs(config) -> dict:
    """PlannedPipeline consumes these through OntologyMapper.map_term()."""
    return {
        "rag_top_k": getattr(config, "rag_top_k", _PLANNED_RAG_TOP_K),
        "max_candidates": getattr(config, "max_candidates", _PLANNED_MAX_CANDIDATES),
        "max_alternatives": getattr(
            config, "max_alternatives", _PLANNED_MAX_ALTERNATIVES
        ),
    }


def _build_llm_provider(config):
    """Build the LLM provider explicitly so local planned mode can share it."""
    from llm_ontology_mapper import LLMProviderFactory  # type: ignore[import-untyped]

    return LLMProviderFactory.from_config(
        provider=_normalise_provider(config.provider),
        model=config.model,
        api_key=get_sensitive("api_key"),
        **_provider_extra_kwargs(config),
    )


def _build_public_retriever(config):
    from llm_ontology_mapper import (  # type: ignore[import-untyped]
        PublicOntologyRetriever,
        PublicRetrievalError,
    )
    from llm_ontology_mapper.search_tools import (  # type: ignore[import-untyped]
        SearchTools,
    )

    credentials = get_validated_loinc_credentials(config)
    loinc_username, loinc_password = credentials or ("", "")

    class BridgePublicOntologyRetriever(PublicOntologyRetriever):
        def _call_route(
            self,
            query: str,
            ontology: str,
            top_k: int,
            *,
            route_diagnostics: dict[str, Any] | None = None,
        ):
            if _is_loinc_ontology(ontology) and credentials is None:
                raise PublicRetrievalError(_LOINC_CREDENTIALS_REQUIRED_MESSAGE)
            return super()._call_route(
                query, ontology, top_k, route_diagnostics=route_diagnostics
            )

    retriever_cls = PublicOntologyRetriever if credentials else BridgePublicOntologyRetriever
    return retriever_cls(
        search_tools=SearchTools(
            loinc_username=loinc_username,
            loinc_password=loinc_password,
        )
    )


def _build_llm_call_config(config):
    """Explicit reasoning override forwarded to every LLM call the planned
    pipeline makes (QueryPlanner + LLMReranker), when the user has selected
    an OpenAI reasoning effort in Settings.

    strict=True: this represents an explicit user configuration, not an
    internal default — if OpenAI rejects it, the call must fail rather than
    the library silently retrying without reasoning_effort and succeeding
    with a configuration the user didn't choose.
    """
    if config.provider != "openai" or not config.reasoning_effort:
        return None

    from llm_ontology_mapper.providers import LLMCallConfig  # type: ignore[import-untyped]

    return LLMCallConfig(reasoning_effort=config.reasoning_effort, strict=True)


def _build_planned_pipeline(config, *, local_retriever=None):
    from llm_ontology_mapper import PlannedPipeline  # type: ignore[import-untyped]

    llm_provider = _build_llm_provider(config)
    return llm_provider, PlannedPipeline(
        provider=llm_provider,
        public_retriever=_build_public_retriever(config),
        local_retriever=local_retriever,
        llm_call_config=_build_llm_call_config(config),
    )


def _build_mapper_kwargs(config, *, ontologies: list[str] | None = None) -> tuple[dict, str | None]:
    """Build OntologyMapper constructor kwargs for the planned pipeline."""
    loinc_credentials = get_validated_loinc_credentials(config)
    if config.retrieval_mode == "public":
        effective_ontologies, warning = _filter_unavailable_loinc_ontology(
            ontologies,
            has_validated_loinc_credentials=loinc_credentials is not None,
        )
    else:
        effective_ontologies, warning = ontologies, None
    kwargs: dict = {
        "ontologies": effective_ontologies,
        "use_planned_pipeline": True,
        "retrieval_mode": config.retrieval_mode,
        **_planned_limit_kwargs(config),
    }

    if config.retrieval_mode == "local":
        from llm_ontology_mapper import (  # type: ignore[import-untyped]
            LocalSemanticRetriever,
        )

        llm_provider, planned_pipeline = _build_planned_pipeline(
            config,
            local_retriever=LocalSemanticRetriever(
                sapbert_url=config.sapbert_server_url,
            ),
        )
        kwargs["llm_provider"] = llm_provider
        kwargs["planned_pipeline"] = planned_pipeline
        return kwargs, warning

    if config.retrieval_mode in {"public", "disabled"}:
        llm_provider, planned_pipeline = _build_planned_pipeline(config)
        kwargs["llm_provider"] = llm_provider
        kwargs["planned_pipeline"] = planned_pipeline
        return kwargs, warning

    kwargs.update(
        {
            "provider": _normalise_provider(config.provider),
            "model": config.model,
            "api_key": get_sensitive("api_key"),
            **_provider_extra_kwargs(config),
        }
    )
    return kwargs, warning


def _bridge_mapping_values(result) -> tuple[str, str, str]:
    """Normalize planned-pipeline unmapped values to Bridge's legacy convention."""
    target_code = result.target_code
    target_term = result.target_term
    ontology = result.ontology
    if target_code == "UNKNOWN:UNMAPPED":
        return "UNMAPPED", "UNMAPPED", ""
    return target_code, target_term, ontology


def _ontology_matches_allow_list(ontology: str, allowed: list[str] | None) -> bool:
    if not allowed:
        return True
    if any(
        _normalize_for_comparison(allowed_ontology) == "EFO"
        for allowed_ontology in allowed
    ):
        return True
    normalized_ontology = _normalize_for_comparison(ontology)
    return normalized_ontology in {
        _normalize_for_comparison(allowed_ontology) for allowed_ontology in allowed
    }


def map_single_term(request: SingleMappingRequest) -> SingleMappingResponse:
    from llm_ontology_mapper import OntologyMapper  # type: ignore[import-untyped]

    _validate_config()
    config = load_config()

    # Fix 2: normalise clinical area → library entity_type
    mapped_entity_type = _map_entity_type(request.entity_type)
    print(
        f"[mapper_service] mapped entity_type: "
        f"'{request.entity_type}' → '{mapped_entity_type}'"
    )

    # Fix 1: use the human-readable label as the retrieval query when present
    effective_term = request.source_label or request.source_term
    print(
        f"[mapper_service] effective_term='{effective_term}' "
        f"(source_term='{request.source_term}' "
        f"source_label='{request.source_label}')"
    )

    # Fix 5: normalise provider string before passing to library factory
    normalised_provider = _normalise_provider(config.provider)
    if normalised_provider != config.provider:
        print(
            f"[mapper_service] provider normalised: "
            f"'{config.provider}' → '{normalised_provider}'"
        )

    mapper_kwargs, mapping_warning = _build_mapper_kwargs(
        config,
        ontologies=request.target_ontologies,
    )
    if "base_url" in mapper_kwargs:
        print(
            f"[mapper_service] base_url: config={config.base_url!r} "
            f"→ effective={mapper_kwargs['base_url']!r}"
        )

    mapper = OntologyMapper(**mapper_kwargs)
    result = mapper.map_term(
        source_term=effective_term,  # Fix 1: label-first query
        source_label=request.source_label,
        source_type=request.source_type,
        entity_type=mapped_entity_type,  # Fix 2: normalised entity type
        source_description=request.source_description,
        strict_target_ontology=request.strict_target_ontology,
    )

    alternatives = [
        AlternativeResult(
            code=a.code,
            term=a.term,
            ontology=a.ontology,
            confidence=a.confidence,
            source=getattr(a, "source", None),
            explanation=getattr(a, "explanation", None),
            url=resolve_ontology_url(a.code, a.ontology),
        )
        for a in result.alternatives
    ]

    metadata: MappingMetadata | None = None
    if result.metadata:
        m = result.metadata
        metadata = MappingMetadata(
            model=m.model,
            provider=m.provider,
            latency_ms=m.latency_ms,
            timestamp=m.timestamp,
            prompt_tokens=getattr(m, "prompt_tokens", None),
            completion_tokens=getattr(m, "completion_tokens", None),
        )

    logic_type_val = result.logic_type
    if hasattr(logic_type_val, "value"):
        logic_type_val = logic_type_val.value
    target_code, target_term, ontology = _bridge_mapping_values(result)

    return SingleMappingResponse(
        source_term=request.source_term,  # always the original variable name
        source_label=request.source_label,
        source_type=request.source_type,
        target_code=target_code,
        target_term=target_term,
        ontology=ontology,
        confidence=result.confidence,
        logic_type=str(logic_type_val),
        notes=_append_mapping_warning(result.notes, mapping_warning),
        alternatives=alternatives,
        metadata=metadata,
        configured_provider=config.provider,
        configured_model=config.model,
        retrieval_mode=config.retrieval_mode,
        target_url=resolve_ontology_url(target_code, ontology),
    )


# ── Batch job functions ──────────────────────────────────────────────────────


def start_batch_job(
    records: list[dict[str, Any]],
    column_map: dict,
    clinical_area: str | None,
    target_ontologies: list[str] | None,
    auto_accept_threshold: float,
    target_ontology_column: str | None = None,
    row_target_ontologies: list[str] | None = None,
    original_columns: list[str] | None = None,
    session_id: str | None = None,
    strict_target_ontology: bool = False,
) -> str:
    job_id = str(uuid.uuid4())
    normalized_target_ontologies = normalize_target_ontologies(target_ontologies)
    per_row_target_ontologies = (
        row_target_ontologies if row_target_ontologies is not None else None
    )
    if per_row_target_ontologies is not None and len(per_row_target_ontologies) != len(
        records
    ):
        raise ValueError("row_target_ontologies must match the number of batch records")
    with _batch_jobs_lock:
        _batch_jobs[job_id] = {
            "status": "running",
            "total": len(records),
            "completed": 0,
            "results": [],
            "target_ontologies": normalized_target_ontologies,
            "target_ontology_column": target_ontology_column,
            "original_columns": original_columns or [],
            "cancel_requested": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
        }

    def run():
        from llm_ontology_mapper import (  # type: ignore[import-untyped]
            OntologyMapper,
            PlannedPipelineError,
        )

        from app.models.mapping import BatchRowResult

        def mark_interrupted() -> tuple[str, str, dict] | None:
            with _batch_jobs_lock:
                job = _batch_jobs.get(job_id)
                if not job:
                    return None
                _mark_batch_interrupted_locked(job)
                logger.info(
                    "[batch:%s] terminal status=interrupted completed=%s/%s",
                    job_id,
                    job["completed"],
                    job["total"],
                )
                return _terminal_history_snapshot_locked(job_id, job)

        def cancellation_requested() -> bool:
            with _batch_jobs_lock:
                job = _batch_jobs.get(job_id)
                return bool(
                    job
                    and (
                        job.get("cancel_requested")
                        or job.get("status") == "interrupted"
                    )
                )

        # Build each distinct mapper allow-list once, then reuse it for matching rows.
        try:
            _validate_config()
            config = load_config()
            mapped_entity_type = _map_entity_type(clinical_area)
            mapper_cache: dict[tuple[str, ...], tuple[Any, str | None]] = {}

            def mapper_for(
                effective_target_ontologies: list[str] | None,
            ) -> tuple[Any, str | None]:
                key = tuple(effective_target_ontologies or [])
                cached = mapper_cache.get(key)
                if cached:
                    return cached

                mapper_kwargs, mapping_warning = _build_mapper_kwargs(
                    config,
                    ontologies=effective_target_ontologies,
                )
                cached = (OntologyMapper(**mapper_kwargs), mapping_warning)
                mapper_cache[key] = cached
                return cached

            if per_row_target_ontologies is not None:
                for ontology in dict.fromkeys(per_row_target_ontologies):
                    mapper_for([ontology])
            else:
                mapper_for(normalized_target_ontologies)
        except Exception as exc:  # noqa: BLE001 - preserve batch row failure handling
            logger.error("Batch job %s failed during initialisation: %s", job_id, exc)
            with _batch_jobs_lock:
                job = _batch_jobs.get(job_id)
                if job:
                    _mark_batch_failed_locked(job, str(exc))
                    logger.info(
                        "[batch:%s] terminal status=%s completed=%s/%s",
                        job_id,
                        job["status"],
                        job["completed"],
                        job["total"],
                    )
                    history_snapshot = _terminal_history_snapshot_locked(job_id, job)
                else:
                    history_snapshot = None
            _persist_terminal_batch_history(job_id, history_snapshot)
            return

        for i, rec in enumerate(records):
            if cancellation_requested():
                _persist_terminal_batch_history(job_id, mark_interrupted())
                return
            field_name_col = column_map.get("field_name") or "field_name"
            label_col = column_map.get("label")
            desc_col = column_map.get("description")
            dtype_col = column_map.get("data_type")

            field_name = rec.get(field_name_col, f"row_{i}")
            label = rec.get(label_col) if label_col else None
            description = rec.get(desc_col) if desc_col else None
            source_type = rec.get(dtype_col) if dtype_col else None

            effective_label = label or description
            effective_term = effective_label or field_name
            effective_target_ontologies = (
                [per_row_target_ontologies[i]]
                if per_row_target_ontologies is not None
                else normalized_target_ontologies
            )
            requested_target_ontology = (
                effective_target_ontologies[0]
                if per_row_target_ontologies is not None and effective_target_ontologies
                else ", ".join(effective_target_ontologies or []) or None
            )
            safe_original_row = _json_safe_original_row(rec)
            safe_original_columns = original_columns or list(safe_original_row.keys())
            mapper, mapping_warning = mapper_for(effective_target_ontologies)
            if cancellation_requested():
                _persist_terminal_batch_history(job_id, mark_interrupted())
                return

            print(
                f'[Batch] Mapping term {i + 1}/{len(records)}: "{effective_term}" | '
                f"model: {_normalise_provider(config.provider)} / {config.model} | "
                f"retrieval_mode: {config.retrieval_mode}"
            )

            try:
                result = mapper.map_term(
                    source_term=effective_term,
                    source_label=effective_label,
                    source_description=description,
                    source_type=source_type,
                    entity_type=mapped_entity_type,
                    strict_target_ontology=strict_target_ontology,
                )
                target_code, target_term, ontology = _bridge_mapping_values(result)
                if target_code != "UNMAPPED" and not _ontology_matches_allow_list(
                    ontology,
                    effective_target_ontologies,
                ):
                    target_code = "UNMAPPED"
                    target_term = "UNMAPPED"
                    ontology = ""
                confidence_pct = result.confidence
                decision = (
                    "accepted" if confidence_pct >= auto_accept_threshold else "pending"
                )
                if target_code == "UNMAPPED":
                    decision = "rejected"

                logic_type_val = result.logic_type
                if hasattr(logic_type_val, "value"):
                    logic_type_val = logic_type_val.value

                processing_time_seconds = (
                    result.metadata.latency_ms / 1000.0
                    if result.metadata is not None
                    and result.metadata.latency_ms is not None
                    else None
                )

                alternatives = [
                    AlternativeResult(
                        code=a.code,
                        term=a.term,
                        ontology=a.ontology,
                        confidence=a.confidence,
                        source=getattr(a, "source", None),
                        explanation=getattr(a, "explanation", None),
                        url=resolve_ontology_url(a.code, a.ontology),
                    )
                    for a in result.alternatives
                    if _ontology_matches_allow_list(
                        getattr(a, "ontology", ""),
                        effective_target_ontologies,
                    )
                ]

                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
                    source_description=description,
                    original_row=safe_original_row,
                    original_columns=safe_original_columns,
                    requested_target_ontology=requested_target_ontology,
                    suggested_code=target_code,
                    suggested_term=target_term,
                    ontology=ontology,
                    confidence=result.confidence,
                    logic_type=str(logic_type_val),
                    decision=decision,
                    alternatives=alternatives,
                    configured_provider=config.provider,
                    configured_model=config.model,
                    retrieval_mode=config.retrieval_mode,
                    notes=_append_mapping_warning(
                        getattr(result, "notes", None),
                        mapping_warning,
                    ),
                    suggested_url=resolve_ontology_url(target_code, ontology),
                    processing_time_seconds=processing_time_seconds,
                )
            except PlannedPipelineError as exc:
                logger.exception(
                    "Batch job %s row %s planned pipeline error",
                    job_id,
                    i,
                )
                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
                    source_description=description,
                    original_row=safe_original_row,
                    original_columns=safe_original_columns,
                    requested_target_ontology=requested_target_ontology,
                    suggested_code="UNMAPPED",
                    suggested_term=str(exc) or type(exc).__name__,
                    ontology="",
                    confidence=0.0,
                    logic_type="llm",
                    decision="rejected",
                    notes=str(exc) or type(exc).__name__,
                )
            except Exception as exc:  # noqa: BLE001 - preserve per-row batch errors
                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
                    source_description=description,
                    original_row=safe_original_row,
                    original_columns=safe_original_columns,
                    requested_target_ontology=requested_target_ontology,
                    suggested_code="UNMAPPED",
                    suggested_term=str(exc) or type(exc).__name__,
                    ontology="",
                    confidence=0.0,
                    logic_type="llm",
                    decision="rejected",
                    notes=str(exc) or type(exc).__name__,
                )
            history_snapshot = None
            with _batch_jobs_lock:
                job = _batch_jobs.get(job_id)
                if not job:
                    return
                if job.get("cancel_requested") or job["status"] == "interrupted":
                    _mark_batch_interrupted_locked(job)
                    logger.info(
                        "[batch:%s] terminal status=interrupted completed=%s/%s",
                        job_id,
                        job["completed"],
                        job["total"],
                    )
                    history_snapshot = _terminal_history_snapshot_locked(job_id, job)
                elif job["status"] in _TERMINAL_BATCH_STATUSES:
                    return
                else:
                    job["results"].append(row)
                    job["completed"] = len(job["results"])
            if history_snapshot is not None:
                _persist_terminal_batch_history(job_id, history_snapshot)
                return

        history_snapshot = None
        with _batch_jobs_lock:
            job = _batch_jobs.get(job_id)
            if not job:
                return
            _mark_batch_done_locked(job)
            logger.info(
                "[batch:%s] terminal status=%s completed=%s/%s",
                job_id,
                job["status"],
                job["completed"],
                job["total"],
            )
            history_snapshot = _terminal_history_snapshot_locked(job_id, job)
        _persist_terminal_batch_history(job_id, history_snapshot)

    threading.Thread(target=run, daemon=True).start()
    return job_id


def get_batch_job(job_id: str) -> dict | None:
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return None
        return {**job, "results": list(job["results"])}


def cancel_batch_job(job_id: str) -> bool:
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return False
        if job["status"] in {"done", "failed"}:
            return True
        _mark_batch_interrupted_locked(job)
        logger.info("[batch:%s] cancellation requested", job_id)
        return True


def update_batch_decision(job_id: str, row_index: int, decision: str) -> bool:
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return False
        for row in job["results"]:
            if row.row_index == row_index:
                row.decision = decision
                return True
        return False


def _candidate_key(*, code: str, ontology: str | None) -> str:
    return f"{ontology or ''}::{code}".strip().lower()


def _row_primary_to_alternative(row) -> AlternativeResult:
    return AlternativeResult(
        code=row.suggested_code,
        term=row.suggested_term,
        ontology=row.ontology,
        confidence=row.confidence,
        source=row.logic_type,
        explanation=row.notes,
        url=row.suggested_url,
    )


def promote_batch_alternative(
    job_id: str,
    row_index: int,
    alternative_code: str,
    alternative_ontology: str | None = None,
):
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return None

        for row in job["results"]:
            if row.row_index != row_index:
                continue

            selected = None
            for alternative in row.alternatives:
                if alternative.code != alternative_code:
                    continue
                if (
                    alternative_ontology is not None
                    and alternative.ontology != alternative_ontology
                ):
                    continue
                selected = alternative
                break
            if selected is None:
                return None

            demoted = _row_primary_to_alternative(row)
            selected_key = _candidate_key(
                code=selected.code,
                ontology=selected.ontology,
            )
            demoted_key = _candidate_key(
                code=demoted.code,
                ontology=demoted.ontology,
            )
            should_demote_primary = row.suggested_code.upper().find("UNMAPPED") == -1

            next_alternatives: list[AlternativeResult] = []
            for alternative in row.alternatives:
                key = _candidate_key(
                    code=alternative.code,
                    ontology=alternative.ontology,
                )
                if key == selected_key:
                    if should_demote_primary:
                        next_alternatives.append(demoted)
                    continue
                if should_demote_primary and key == demoted_key:
                    continue
                next_alternatives.append(alternative)

            row.suggested_code = selected.code
            row.suggested_term = selected.term
            row.ontology = selected.ontology
            row.confidence = selected.confidence
            row.logic_type = selected.source or row.logic_type
            row.notes = selected.explanation
            row.decision = "pending"
            row.alternatives = next_alternatives
            row.suggested_url = selected.url
            return row

        return None
