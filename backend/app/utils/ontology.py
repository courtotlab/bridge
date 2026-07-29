from typing import Any

_AUTO_VALUES = {"auto", "auto-detect"}


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

        key = ontology.lower()
        if key in seen:
            continue
        normalized.append(ontology)
        seen.add(key)

    return normalized or None
