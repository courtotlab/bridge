import asyncio
import logging
import os
import re

import httpx

from app.models.validator import ValidateResult

logger = logging.getLogger(__name__)

_OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"

# Prefix → display ontology name for colon-separated OBO-style codes
_OBO_DISPLAY: dict[str, str] = {
    "HP": "HPO",
    "MONDO": "MONDO",
    "DOID": "DOID",
    "CHEBI": "ChEBI",
    "GO": "GO",
    "NCIT": "NCIT",
    "UBERON": "UBERON",
    "CL": "CL",
    "MP": "MPO",
    "EFO": "EFO",
    "ORDO": "ORDO",
    "OMIM": "OMIM",
    "SNOMED": "SNOMED CT",
    "SNOMEDCT": "SNOMED CT",
    "MAXO": "MAxO",
}

# Bare LOINC codes look like  12345-6  (1–5 digits, hyphen, 1 digit check digit)
_LOINC_BARE = re.compile(r"^\d{1,5}-\d$")


def _classify(raw: str) -> tuple[str, str]:
    """Return (kind, normalised_code). kind is 'loinc', 'ols4', or 'unknown'."""
    code = raw.strip()
    upper = code.upper()
    if upper.startswith("LOINC:"):
        return "loinc", upper.removeprefix("LOINC:")
    if _LOINC_BARE.match(upper):
        return "loinc", upper
    if ":" in code:
        return "ols4", code
    return "unknown", code


async def _lookup_unknown(code: str) -> ValidateResult:
    return ValidateResult(code=code, status="not-found")


async def _lookup_ols4(
    code: str,
    sem: asyncio.Semaphore,
    http: httpx.AsyncClient,
) -> ValidateResult:
    async with sem:
        try:
            resp = await http.get(
                f"{_OLS4_BASE}/terms",
                params={"id": code, "exact": "true"},
                timeout=10.0,
            )
        except Exception:
            logger.exception("OLS4 network error for %s", code)
            return ValidateResult(code=code, status="not-found")

        if resp.status_code != 200:
            return ValidateResult(code=code, status="not-found")

        try:
            terms = resp.json().get("_embedded", {}).get("terms", [])
        except Exception:
            logger.exception("OLS4 JSON parse error for %s", code)
            return ValidateResult(code=code, status="not-found")

        if not terms:
            return ValidateResult(code=code, status="not-found")

        t = terms[0]
        prefix = code.split(":")[0].upper()
        ontology = _OBO_DISPLAY.get(prefix, prefix)
        status: str = "deprecated" if t.get("is_obsolete") else "valid"
        return ValidateResult(
            code=code,
            status=status,  # type: ignore[arg-type]
            term=t.get("label"),
            ontology=ontology,
        )


async def _lookup_loinc(
    original_code: str,
    loinc_code: str,
    sem: asyncio.Semaphore,
    http: httpx.AsyncClient,
    username: str,
    password: str,
) -> ValidateResult:
    async with sem:
        try:
            resp = await http.get(
                "https://fhir.loinc.org/CodeSystem/$lookup",
                params={"system": "http://loinc.org", "code": loinc_code},
                auth=(username, password),
                timeout=10.0,
            )
        except Exception:
            logger.exception("LOINC FHIR network error for %s", original_code)
            return ValidateResult(code=original_code, status="not-found")

        if resp.status_code == 404:
            return ValidateResult(code=original_code, status="not-found")
        if resp.status_code != 200:
            logger.warning(
                "LOINC FHIR returned %s for %s", resp.status_code, original_code
            )
            return ValidateResult(code=original_code, status="not-found")

        try:
            params = resp.json().get("parameter", [])
        except Exception:
            logger.exception("LOINC FHIR JSON parse error for %s", original_code)
            return ValidateResult(code=original_code, status="not-found")

        display = next(
            (p.get("valueString") for p in params if p.get("name") == "display"),
            None,
        )
        return ValidateResult(
            code=original_code,
            status="valid",
            term=display,
            ontology="LOINC",
        )


async def validate_codes(codes: list[str]) -> list[ValidateResult]:
    loinc_user = os.environ.get("LOINC_USERNAME")
    loinc_pass = os.environ.get("LOINC_PASSWORD")

    sem = asyncio.Semaphore(10)

    async with httpx.AsyncClient() as http:
        tasks: list[asyncio.coroutine] = []
        for raw in codes:
            kind, normalised = _classify(raw)
            if kind == "loinc":
                if loinc_user and loinc_pass:
                    tasks.append(
                        _lookup_loinc(raw, normalised, sem, http, loinc_user, loinc_pass)
                    )
                else:
                    tasks.append(_lookup_unknown(raw))
            elif kind == "ols4":
                tasks.append(_lookup_ols4(raw, sem, http))
            else:
                tasks.append(_lookup_unknown(raw))

        return list(await asyncio.gather(*tasks))
