import logging
import uuid
from typing import Any

from app.models.mapping import (
    AlternativeResult,
    MappingMetadata,
    SingleMappingRequest,
    SingleMappingResponse,
)
from app.storage.config_store import get_sensitive, load_config

# ── Batch job store ──────────────────────────────────────────────────────────
_batch_jobs: dict[str, dict] = {}

logger = logging.getLogger(__name__)

_CLOUD_PROVIDERS = {"openai", "anthropic", "ollama_cloud"}
_OLLAMA_PROVIDERS = {"ollama", "ollama_cloud"}
_OLLAMA_CLOUD_BASE = "https://ollama.com"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
_PLANNED_RAG_TOP_K = 5
_PLANNED_MAX_CANDIDATES = 10
_PLANNED_MAX_ALTERNATIVES = 5

# Fix 2: frontend option values (lowercase, "/" → "_") → library entity_type
_CLINICAL_AREA_MAP: dict[str, str | None] = {
    "phenotype_symptom": "phenotype",
    "disease_condition":  "disease",
    "lab_measurement":    "measurement",
    "medication":         "medication",
    "demographic":        "demographic",
    "other":              "other",
    # pass-through for callers that already use library values
    "phenotype":   "phenotype",
    "disease":     "disease",
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
    "HP": "HPO",      "HPO": "HPO",
    "MONDO": "MONDO",
    "NCIT": "NCIT",
    "LOINC": "LOINC",
    "ICD10": "ICD10", "ICD10CM": "ICD10",
    "CHEBI": "CHEBI",
    "SNOMED": "SNOMED", "SNOMEDCT": "SNOMED", "SNOMED-CT": "SNOMED",
    "RXNORM": "RXNORM",
}


def _normalize_for_comparison(o: str | None) -> str:
    if not o:
        return ""
    upper = o.upper().strip()
    return _ONTOLOGY_COMPARE_NORMALIZE.get(upper, upper)


def _infer_ontology_from_code(code: str) -> str:
    """Derive a canonical ontology label from a CURIE prefix."""
    if not code or ":" not in code:
        return code
    prefix = code.split(":", 1)[0].upper()
    return {
        "HP": "HPO",   "HPO": "HPO",
        "MONDO": "MONDO",
        "NCIT": "NCIT",
        "LOINC": "LOINC",
        "ICD10": "ICD10",  "ICD10CM": "ICD10",
        "RXNORM": "RxNorm", "RXCUI": "RxNorm",
        "SNOMEDCT": "SNOMED-CT", "SNOMED": "SNOMED-CT",
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
        "rag_top_k":        getattr(config, "rag_top_k", _PLANNED_RAG_TOP_K),
        "max_candidates":   getattr(config, "max_candidates", _PLANNED_MAX_CANDIDATES),
        "max_alternatives": getattr(config, "max_alternatives", _PLANNED_MAX_ALTERNATIVES),
    }


def _build_llm_provider(config):
    """Build the LLM provider explicitly so local planned mode can share it."""
    from llm_ontology_mapper import LLMProviderFactory

    return LLMProviderFactory.from_config(
        provider=_normalise_provider(config.provider),
        model=config.model,
        api_key=get_sensitive("api_key"),
        **_provider_extra_kwargs(config),
    )


def _build_mapper_kwargs(config, *, ontologies: list[str] | None = None) -> dict:
    """Build OntologyMapper constructor kwargs for the planned pipeline."""
    kwargs: dict = {
        "ontologies":            ontologies,
        "use_planned_pipeline":  True,
        "retrieval_mode":        config.retrieval_mode,
        **_planned_limit_kwargs(config),
    }

    if config.retrieval_mode == "local":
        from llm_ontology_mapper import LocalSemanticRetriever, PlannedPipeline

        llm_provider = _build_llm_provider(config)
        kwargs["llm_provider"] = llm_provider
        kwargs["planned_pipeline"] = PlannedPipeline(
            provider=llm_provider,
            local_retriever=LocalSemanticRetriever(
                sapbert_url=config.sapbert_server_url,
            ),
        )
        return kwargs

    kwargs.update({
        "provider": _normalise_provider(config.provider),
        "model":    config.model,
        "api_key":  get_sensitive("api_key"),
        **_provider_extra_kwargs(config),
    })
    return kwargs


def _bridge_mapping_values(result) -> tuple[str, str, str]:
    """Normalize planned-pipeline unmapped values to Bridge's legacy convention."""
    target_code = result.target_code
    target_term = result.target_term
    ontology = result.ontology
    if target_code == "UNKNOWN:UNMAPPED":
        return "UNMAPPED", "UNMAPPED", ""
    return target_code, target_term, ontology


def map_single_term(request: SingleMappingRequest) -> SingleMappingResponse:
    from llm_ontology_mapper import OntologyMapper

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

    # Per-request ontology filter (None = auto-detect via entity_type)
    ontologies: list[str] | None = None
    if request.target_ontologies and request.target_ontologies.lower() != "auto":
        ontologies = [request.target_ontologies.upper()]

    mapper_kwargs = _build_mapper_kwargs(config, ontologies=ontologies)
    if "base_url" in mapper_kwargs:
        print(
            f"[mapper_service] base_url: config={config.base_url!r} "
            f"→ effective={mapper_kwargs['base_url']!r}"
        )

    mapper = OntologyMapper(**mapper_kwargs)
    result = mapper.map_term(
        source_term=effective_term,        # Fix 1: label-first query
        source_label=request.source_label,
        source_type=request.source_type,
        entity_type=mapped_entity_type,    # Fix 2: normalised entity type
    )

    alternatives = [
        AlternativeResult(
            code=a.code,
            term=a.term,
            ontology=a.ontology,
            confidence=a.confidence,
            source=getattr(a, "source", "llm"),
            explanation=getattr(a, "explanation", None),
        )
        for a in result.alternatives
    ]

    # ── Layer 2: ontology filter / promote / fallback ────────────────────────
    # When a specific ontology is selected, every returned item must belong to
    # that ontology. Auto-detect (ontologies is None) skips this block entirely.
    if ontologies is not None:
        selected = _normalize_for_comparison(ontologies[0])

        def _ont_of_result() -> str:
            return _normalize_for_comparison(result.ontology) or \
                   _normalize_for_comparison(_infer_ontology_from_code(result.target_code))

        def _ont_of_alt(alt: AlternativeResult) -> str:
            return _normalize_for_comparison(alt.ontology) or \
                   _normalize_for_comparison(_infer_ontology_from_code(alt.code))

        filtered_alts = [a for a in alternatives if _ont_of_alt(a) == selected]

        if _ont_of_result() == selected:
            alternatives = filtered_alts
        elif filtered_alts:
            # Promote the highest-confidence matching alternative to best match.
            best_alt = filtered_alts[0]
            from llm_ontology_mapper.models import LogicType as _LogicType
            result = result.model_copy(update={
                "target_code":  best_alt.code,
                "target_term":  best_alt.term,
                "ontology":     best_alt.ontology,
                "confidence":   best_alt.confidence,
                "logic_type":   _LogicType(best_alt.source) if best_alt.source in ("llm", "rag", "direct") else _LogicType.LLM,
            })
            alternatives = filtered_alts[1:]
            print(f"[mapper_service] ontology filter: promoted {best_alt.code} from alternatives")
        else:
            print(f"[mapper_service] ontology filter: no match for '{selected}' — returning UNMAPPED")
            return SingleMappingResponse(
                source_term=request.source_term,
                source_label=request.source_label,
                source_type=request.source_type,
                target_code="UNMAPPED",
                target_term="NO_MATCH_IN_SELECTED_ONTOLOGY",
                ontology=ontologies[0],
                confidence=0.0,
                logic_type="llm",
                notes=f"No match found in {ontologies[0]}. Try Auto-detect or a different ontology.",
                alternatives=[],
                metadata=None,
                configured_provider=config.provider,
                configured_model=config.model,
                retrieval_mode=config.retrieval_mode,
            )

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
        source_term=request.source_term,   # always the original variable name
        source_label=request.source_label,
        source_type=request.source_type,
        target_code=target_code,
        target_term=target_term,
        ontology=ontology,
        confidence=result.confidence,
        logic_type=str(logic_type_val),
        notes=result.notes,
        alternatives=alternatives,
        metadata=metadata,
        configured_provider=config.provider,
        configured_model=config.model,
        retrieval_mode=config.retrieval_mode,
    )


# ── Batch job functions ──────────────────────────────────────────────────────

def start_batch_job(
    records: list[dict[str, Any]],
    column_map: dict,
    clinical_area: str | None,
    auto_accept_threshold: float,
) -> str:
    import threading
    job_id = str(uuid.uuid4())
    _batch_jobs[job_id] = {
        "status": "running",
        "total": len(records),
        "completed": 0,
        "results": [],
        "cancel": False,
    }

    def run():
        from app.models.mapping import BatchRowResult
        from llm_ontology_mapper import OntologyMapper

        # Initialise once for the entire batch — not once per term.
        try:
            _validate_config()
            config = load_config()
            mapped_entity_type = _map_entity_type(clinical_area)
            mapper = OntologyMapper(**_build_mapper_kwargs(config))
        except Exception as exc:
            logger.error("Batch job %s failed during initialisation: %s", job_id, exc)
            _batch_jobs[job_id]["status"] = "failed"
            return

        job = _batch_jobs[job_id]
        for i, rec in enumerate(records):
            if job["cancel"]:
                job["status"] = "cancelled"
                return
            field_name_col = column_map.get("field_name") or "field_name"
            label_col      = column_map.get("label")
            desc_col       = column_map.get("description")
            dtype_col      = column_map.get("data_type")

            field_name  = rec.get(field_name_col, f"row_{i}")
            label       = rec.get(label_col) if label_col else None
            description = rec.get(desc_col) if desc_col else None
            source_type = rec.get(dtype_col) if dtype_col else None

            effective_label = label or description
            effective_term  = effective_label or field_name

            print(
                f"[Batch] Mapping term {i + 1}/{len(records)}: \"{effective_term}\" | "
                f"model: {_normalise_provider(config.provider)} / {config.model} | "
                f"retrieval_mode: {config.retrieval_mode}"
            )

            try:
                result = mapper.map_term(
                    source_term=effective_term,
                    source_label=effective_label,
                    source_type=source_type,
                    entity_type=mapped_entity_type,
                )
                target_code, target_term, ontology = _bridge_mapping_values(result)
                confidence_pct = result.confidence
                decision = "accepted" if confidence_pct >= auto_accept_threshold else "pending"
                if target_code == "UNMAPPED":
                    decision = "rejected"

                logic_type_val = result.logic_type
                if hasattr(logic_type_val, "value"):
                    logic_type_val = logic_type_val.value

                alternatives = [
                    AlternativeResult(
                        code=a.code,
                        term=a.term,
                        ontology=a.ontology,
                        confidence=a.confidence,
                        source=getattr(a, "source", "llm"),
                        explanation=getattr(a, "explanation", None),
                    )
                    for a in result.alternatives
                ]

                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
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
                )
            except Exception as exc:
                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
                    suggested_code="UNMAPPED",
                    suggested_term=str(exc) or type(exc).__name__,
                    ontology="",
                    confidence=0.0,
                    logic_type="llm",
                    decision="rejected",
                )
            job["results"].append(row)
            job["completed"] = i + 1
        job["status"] = "done"

    threading.Thread(target=run, daemon=True).start()
    return job_id


def get_batch_job(job_id: str) -> dict | None:
    return _batch_jobs.get(job_id)


def cancel_batch_job(job_id: str) -> bool:
    job = _batch_jobs.get(job_id)
    if job:
        job["cancel"] = True
        return True
    return False


def update_batch_decision(job_id: str, row_index: int, decision: str) -> bool:
    job = _batch_jobs.get(job_id)
    if not job:
        return False
    for row in job["results"]:
        if row.row_index == row_index:
            row.decision = decision
            return True
    return False
