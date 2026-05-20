import logging

from app.models.mapping import (
    AlternativeResult,
    MappingMetadata,
    SingleMappingRequest,
    SingleMappingResponse,
)
from app.storage.config_store import get_sensitive, load_config

logger = logging.getLogger(__name__)

_CLOUD_PROVIDERS = {"openai", "anthropic", "ollama_cloud"}
_OLLAMA_PROVIDERS = {"ollama", "ollama_cloud"}

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
        mapper_kwargs["base_url"] = config.base_url

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
