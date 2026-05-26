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


def _build_retriever(config):
    """Construct an OntologyRetriever from config, or None when retrieval is disabled."""
    from llm_ontology_mapper import OntologyRetriever
    if config.retrieval_mode == "disabled":
        return None
    kwargs: dict = {
        "bioportal_api_key": get_sensitive("bioportal_api_key"),
        "loinc_fhir_user":   config.loinc_username,
        "loinc_fhir_pass":   get_sensitive("loinc_password"),
    }
    if config.retrieval_mode == "local":
        kwargs["sapbert_url"] = config.sapbert_server_url
    return OntologyRetriever(**kwargs)


def _build_mapper_kwargs(config, retriever, *, ontologies: list[str] | None = None) -> dict:
    """Build OntologyMapper constructor kwargs from config and a pre-built retriever."""
    kwargs: dict = {
        "provider":                  _normalise_provider(config.provider),
        "model":                     config.model,
        "api_key":                   get_sensitive("api_key"),
        "ontologies":                ontologies,
        "use_rag":                   config.retrieval_mode != "disabled",
        "ontology_retriever":        retriever,
        "rag_auto_accept_threshold": config.rag_auto_accept_threshold,
    }
    if config.provider in _OLLAMA_PROVIDERS:
        from urllib.parse import urlparse
        raw = (config.base_url or "").rstrip("/")
        host = urlparse(raw).hostname or "" if raw else ""
        effective_base = (
            _OLLAMA_CLOUD_BASE
            if config.provider == "ollama_cloud" and (not raw or host in _LOCAL_HOSTS)
            else raw or None
        )
        kwargs["base_url"] = effective_base
    return kwargs


def map_single_term(request: SingleMappingRequest) -> SingleMappingResponse:
    from llm_ontology_mapper import OntologyMapper, OntologyRetriever
    from llm_ontology_mapper.models import LogicType

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

    retriever = None
    if config.retrieval_mode != "disabled":
        retriever_kwargs: dict = {
            "bioportal_api_key": get_sensitive("bioportal_api_key"),
            "loinc_fhir_user":   config.loinc_username,
            "loinc_fhir_pass":   get_sensitive("loinc_password"),
        }
        if config.retrieval_mode == "local":
            retriever_kwargs["sapbert_url"] = config.sapbert_server_url
        retriever = OntologyRetriever(**retriever_kwargs)

    # Per-request ontology filter (None = auto-detect via entity_type)
    ontologies: list[str] | None = None
    if request.target_ontologies and request.target_ontologies.lower() != "auto":
        ontologies = [request.target_ontologies.upper()]

    mapper_kwargs: dict = {
        "provider":                normalised_provider,
        "model":                   config.model,
        "api_key":                 get_sensitive("api_key"),
        "ontologies":              ontologies,
        "use_rag":                 config.retrieval_mode != "disabled",
        "ontology_retriever":      retriever,
        "rag_auto_accept_threshold": config.rag_auto_accept_threshold,
    }
    if config.provider in _OLLAMA_PROVIDERS:
        from urllib.parse import urlparse
        raw = (config.base_url or "").rstrip("/")
        host = urlparse(raw).hostname or "" if raw else ""
        effective_base = (
            _OLLAMA_CLOUD_BASE
            if config.provider == "ollama_cloud" and (not raw or host in _LOCAL_HOSTS)
            else raw or None
        )
        mapper_kwargs["base_url"] = effective_base
        print(f"[mapper_service] base_url: config={config.base_url!r} → effective={effective_base!r}")

    mapper = OntologyMapper(**mapper_kwargs)
    result = mapper.map_term(
        source_term=effective_term,        # Fix 1: label-first query
        source_label=request.source_label,
        source_type=request.source_type,
        entity_type=mapped_entity_type,    # Fix 2: normalised entity type
    )

    # Fix 4: enforce rag_auto_accept_threshold in the service layer
    # (the library stores this flag in debug metadata but never acts on it)
    rag_debug = result.metadata.rag_debug if result.metadata else None
    if (
        rag_debug
        and rag_debug.auto_accepted
        and rag_debug.candidates_retrieved
    ):
        top = rag_debug.candidates_retrieved[0]
        top_score = float(top.get("score", 0.0))
        threshold = config.rag_auto_accept_threshold
        should_override = (
            result.target_code == "UNMAPPED"
            or result.confidence < top_score
        )
        print(
            f"[mapper_service] auto_accept: top_score={top_score} "
            f"threshold={threshold} accepted={should_override}"
        )
        if should_override:
            top_code = top.get("code", result.target_code)
            result = result.model_copy(update={
                "target_code": top_code,
                "target_term": top.get("term", result.target_term),
                "ontology":    _infer_ontology_from_code(top_code),
                "confidence":  round(top_score, 3),
                "logic_type":  LogicType.RAG,
            })
    else:
        top_score = 0.0
        threshold = config.rag_auto_accept_threshold
        print(
            f"[mapper_service] auto_accept: top_score={top_score} "
            f"threshold={threshold} accepted=False"
        )

    # Fix 3: build alternatives from RAG candidates when library returns []
    # (the library asks the LLM for alternatives but never reads them from JSON)
    if not result.alternatives and rag_debug and rag_debug.candidates_retrieved:
        built: list[AlternativeResult] = []
        for c in rag_debug.candidates_retrieved:
            code = c.get("code", "")
            if code and code != result.target_code:
                built.append(AlternativeResult(
                    code=code,
                    term=c.get("term", ""),
                    ontology=_infer_ontology_from_code(code),
                    confidence=round(float(c.get("score", 0.0)), 3),
                    source="rag",
                ))
        built.sort(key=lambda x: x.confidence, reverse=True)
        alternatives = built[:5]
        alt_source = "rag_debug"
    else:
        alternatives = [
            AlternativeResult(
                code=a.code,
                term=a.term,
                ontology=a.ontology,
                confidence=a.confidence,
                source=getattr(a, "source", "llm"),
            )
            for a in result.alternatives
        ]
        alt_source = "llm" if result.alternatives else "empty"

    print(f"[mapper_service] alternatives built: {len(alternatives)} from {alt_source}")

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

    return SingleMappingResponse(
        source_term=request.source_term,   # always the original variable name
        source_label=request.source_label,
        source_type=request.source_type,
        target_code=result.target_code,
        target_term=result.target_term,
        ontology=result.ontology,
        confidence=result.confidence,
        logic_type=str(logic_type_val),
        notes=result.notes,
        alternatives=alternatives,
        metadata=metadata,
    )


# ── Batch job functions ──────────────────────────────────────────────────────

def start_batch_job(
    records: list[dict[str, Any]],
    column_map: dict,
    clinical_area: str | None,
    use_rag: bool,
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
            retriever = _build_retriever(config)
            mapper = OntologyMapper(**_build_mapper_kwargs(config, retriever))
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
                f"mode: {'no-rag' if config.retrieval_mode == 'disabled' else 'rag'}"
            )

            try:
                result = mapper.map_term(
                    source_term=effective_term,
                    source_label=effective_label,
                    source_type=source_type,
                    entity_type=mapped_entity_type,
                )
                confidence_pct = result.confidence
                decision = "accepted" if confidence_pct >= auto_accept_threshold else "pending"
                if result.target_code == "UNMAPPED":
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
                    )
                    for a in result.alternatives
                ]

                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
                    suggested_code=result.target_code,
                    suggested_term=result.target_term,
                    ontology=result.ontology,
                    confidence=result.confidence,
                    logic_type=str(logic_type_val),
                    decision=decision,
                    alternatives=alternatives,
                )
            except Exception:
                row = BatchRowResult(
                    row_index=i,
                    field_name=field_name,
                    label=effective_label,
                    suggested_code="UNMAPPED",
                    suggested_term="Error",
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
