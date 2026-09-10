"""Deterministic ontology entity URL resolution.

Answers "where should a user browse this CURIE?" from the returned code
alone. This module performs no network I/O, no database access, and has no
dependency on llm_ontology_mapper — it is a pure, stateless string
transformation safe to call from single-term mapping, batch mapping, and
history read paths alike.

It intentionally does NOT answer "does this code exist?" — that is the
separate concern of app.services.validate_service / the mapper's own
OntologyValidator, neither of which is used here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from urllib.parse import quote

_UNMAPPED_VALUES = {"UNMAPPED", "UNKNOWN:UNMAPPED"}

# Runtime CURIE prefix (and known aliases) -> canonical registry key.
# The returned code's own prefix is always preferred; ontology_hint is only
# consulted for a genuinely bare (colon-free) identifier.
_PREFIX_ALIASES: dict[str, str] = {
    "HP": "HP",
    "HPO": "HP",
    "MONDO": "MONDO",
    "EFO": "EFO",
    "NCIT": "NCIT",
    "CHEBI": "CHEBI",
    "SNOMEDCT": "SNOMEDCT",
    "SNOMED": "SNOMEDCT",
    "SNOMED-CT": "SNOMEDCT",
    "SCTID": "SNOMEDCT",
    "LOINC": "LOINC",
    "ICD10": "ICD10",
    "ICD10CM": "ICD10",
    "RXNORM": "RXNORM",
    "RXCUI": "RXNORM",
}

# A local identifier must look like this to be considered safe to embed in a
# URL at all (rejects blanks, embedded colons/whitespace, and other malformed
# CURIE tails) before any ontology-specific validation runs.
_SAFE_LOCAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_NUMERIC_ID_RE = re.compile(r"^[0-9]+$")

_OBO_PURL_BASE = "http://purl.obolibrary.org/obo/"
_OLS4_BASE = "https://www.ebi.ac.uk/ols4/ontologies"


def _is_safe_local_id(local_id: str) -> bool:
    return bool(_SAFE_LOCAL_ID_RE.match(local_id))


def _is_numeric_id(local_id: str) -> bool:
    return bool(_NUMERIC_ID_RE.match(local_id))


def _normalize_prefix(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().upper()
    if not key:
        return None
    return _PREFIX_ALIASES.get(key)


def _ols4_class_url(ols_ontology_id: str, iri: str) -> str:
    """Build an OLS4 human-facing class-page URL from an entity IRI.

    OLS4's frontend route (`/ontologies/{id}/classes/{iri}`) expects the IRI
    double percent-encoded — mirroring the encoding scheme the installed
    llm_ontology_mapper package's own OntologyValidator uses for the
    equivalent (API, not browser) OLS4 route.
    """
    once = quote(iri, safe="")
    twice = quote(once, safe="")
    return f"{_OLS4_BASE}/{ols_ontology_id}/classes/{twice}"


def _obo_ols4_builder(ols_ontology_id: str, obo_prefix: str) -> Callable[[str], str | None]:
    """OBO Foundry PURL ontologies: PREFIX:local -> obo/PREFIX_local, via OLS4."""

    def build(local_id: str) -> str | None:
        if not _is_safe_local_id(local_id):
            return None
        iri = f"{_OBO_PURL_BASE}{obo_prefix}_{local_id}"
        return _ols4_class_url(ols_ontology_id, iri)

    return build


def _efo_url(local_id: str) -> str | None:
    """EFO does not use the generic OBO PURL namespace."""
    if not _is_safe_local_id(local_id):
        return None
    iri = f"http://www.ebi.ac.uk/efo/EFO_{local_id}"
    return _ols4_class_url("efo", iri)


def _snomedct_url(local_id: str) -> str | None:
    """SNOMED CT's IRI is the bare numeric SCTID, not a PREFIX_id form."""
    if not _is_numeric_id(local_id):
        return None
    iri = f"http://snomed.info/id/{local_id}"
    return _ols4_class_url("snomed", iri)


def _loinc_url(local_id: str) -> str | None:
    if not _is_safe_local_id(local_id):
        return None
    return f"https://loinc.org/{quote(local_id, safe='')}"


def _rxnorm_url(local_id: str) -> str | None:
    if not _is_numeric_id(local_id):
        return None
    return f"https://mor.nlm.nih.gov/RxNav/search?searchBy=RXCUI&searchTerm={quote(local_id, safe='')}"


def current_icd10cm_fiscal_year(today: date | None = None) -> int:
    """The applicable CDC/NCHS ICD-10-CM release fiscal year.

    New releases take effect October 1 each year (FY = next calendar year
    from October through December; FY = current calendar year otherwise).
    """
    reference = today or date.today()
    return reference.year + 1 if reference.month >= 10 else reference.year


def _icd10cm_url(local_id: str) -> str | None:
    if not _is_safe_local_id(local_id):
        return None
    fiscal_year = current_icd10cm_fiscal_year()
    return (
        f"https://icd10cmtool.cdc.gov/?fy=FY{fiscal_year}"
        f"&query={quote(local_id, safe='')}"
    )


_REGISTRY: dict[str, Callable[[str], str | None]] = {
    "HP": _obo_ols4_builder("hp", "HP"),
    "MONDO": _obo_ols4_builder("mondo", "MONDO"),
    "NCIT": _obo_ols4_builder("ncit", "NCIT"),
    "CHEBI": _obo_ols4_builder("chebi", "CHEBI"),
    "EFO": _efo_url,
    "SNOMEDCT": _snomedct_url,
    "LOINC": _loinc_url,
    "ICD10": _icd10cm_url,
    "RXNORM": _rxnorm_url,
}


def resolve_ontology_url(code: str | None, ontology_hint: str | None = None) -> str | None:
    """Return a deterministic external browser URL for `code`, or None.

    The returned CURIE prefix is always the primary source of truth —
    `ontology_hint` (e.g. the originally requested ontology, or a sibling
    `ontology` field) is only consulted when `code` has no prefix of its own
    (a genuinely bare identifier). A prefix parsed from `code` itself is
    never overridden by `ontology_hint`, even if that prefix is unsupported
    or unrecognized — in that case this returns None rather than guessing.

    Never raises: any unsupported, malformed, or ambiguous input results in
    None, not an exception or a fabricated link.
    """
    if not isinstance(code, str):
        return None

    stripped = code.strip()
    if not stripped:
        return None
    if stripped.upper() in _UNMAPPED_VALUES:
        return None

    if ":" in stripped:
        raw_prefix, local_id = stripped.split(":", 1)
        prefix = _normalize_prefix(raw_prefix)
        if prefix is None:
            return None
    else:
        prefix = _normalize_prefix(ontology_hint) if ontology_hint else None
        if prefix is None:
            return None
        local_id = stripped

    local_id = local_id.strip()
    if not local_id:
        return None

    builder = _REGISTRY.get(prefix)
    if builder is None:
        return None

    try:
        return builder(local_id)
    except Exception:  # noqa: BLE001 - never let a malformed code raise
        return None
