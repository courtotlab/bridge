from typing import Any

_AUTO_VALUES = {"auto", "auto-detect"}
SUPPORTED_TARGET_ONTOLOGIES = (
    "HPO",
    "MONDO",
    "NCIT",
    "LOINC",
    "ICD10",
    "CHEBI",
    "SNOMED",
    "RxNorm",
)
_CANONICAL_TARGET_ONTOLOGY_BY_KEY = {
    ontology.lower(): ontology for ontology in SUPPORTED_TARGET_ONTOLOGIES
}


def normalize_target_ontology_identifier(value: Any) -> str | None:
    """Return a canonical supported ontology identifier, or None when unknown."""
    if not isinstance(value, str):
        return None

    ontology = value.strip()
    if not ontology or ontology.lower() in _AUTO_VALUES:
        return None

    return _CANONICAL_TARGET_ONTOLOGY_BY_KEY.get(ontology.lower())


def normalize_target_ontologies(value: Any) -> list[str] | None:
    """Normalize Bridge's target ontology input shape without aliasing names."""
    if value is None:
        return None

    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raise TypeError("target_ontologies must be a string, list of strings, or null")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if not isinstance(raw, str):
            raise TypeError("target_ontologies must contain only strings")

        ontology = raw.strip()
        if not ontology or ontology.lower() in _AUTO_VALUES:
            continue

        canonical = normalize_target_ontology_identifier(ontology) or ontology
        key = canonical.lower()
        if key in seen:
            continue
        normalized.append(canonical)
        seen.add(key)

    return normalized or None
