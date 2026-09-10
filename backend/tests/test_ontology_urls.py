from datetime import date

from app.utils.ontology_urls import current_icd10cm_fiscal_year, resolve_ontology_url


def _double_encoded_iri(iri: str) -> str:
    from urllib.parse import quote

    return quote(quote(iri, safe=""), safe="")


class TestOls4Ontologies:
    def test_hp(self):
        url = resolve_ontology_url("HP:0001250")
        expected_iri = _double_encoded_iri("http://purl.obolibrary.org/obo/HP_0001250")
        assert url == f"https://www.ebi.ac.uk/ols4/ontologies/hp/classes/{expected_iri}"

    def test_hpo_alias(self):
        # HPO is never actually returned by the mapper, but the alias should
        # still resolve defensively to the same HP entity.
        assert resolve_ontology_url("HPO:0001250") == resolve_ontology_url("HP:0001250")

    def test_mondo(self):
        url = resolve_ontology_url("MONDO:0005180")
        expected_iri = _double_encoded_iri("http://purl.obolibrary.org/obo/MONDO_0005180")
        assert url == f"https://www.ebi.ac.uk/ols4/ontologies/mondo/classes/{expected_iri}"

    def test_efo_uses_non_obo_iri(self):
        url = resolve_ontology_url("EFO:0004340")
        expected_iri = _double_encoded_iri("http://www.ebi.ac.uk/efo/EFO_0004340")
        assert url == f"https://www.ebi.ac.uk/ols4/ontologies/efo/classes/{expected_iri}"
        # Must NOT use the generic OBO PURL namespace for EFO.
        assert "purl.obolibrary.org" not in url

    def test_ncit(self):
        url = resolve_ontology_url("NCIT:C3224")
        expected_iri = _double_encoded_iri("http://purl.obolibrary.org/obo/NCIT_C3224")
        assert url == f"https://www.ebi.ac.uk/ols4/ontologies/ncit/classes/{expected_iri}"

    def test_chebi(self):
        url = resolve_ontology_url("CHEBI:15377")
        expected_iri = _double_encoded_iri("http://purl.obolibrary.org/obo/CHEBI_15377")
        assert url == f"https://www.ebi.ac.uk/ols4/ontologies/chebi/classes/{expected_iri}"

    def test_snomedct_uses_bare_sctid(self):
        url = resolve_ontology_url("SNOMEDCT:138875005")
        expected_iri = _double_encoded_iri("http://snomed.info/id/138875005")
        assert url == f"https://www.ebi.ac.uk/ols4/ontologies/snomed/classes/{expected_iri}"
        # Must NOT reproduce the installed mapper validator's incorrect
        # "SNOMEDCT_<id>" substitution.
        assert "SNOMEDCT_138875005" not in url

    def test_snomed_alias(self):
        assert resolve_ontology_url("SNOMED:138875005") == resolve_ontology_url(
            "SNOMEDCT:138875005"
        )

    def test_snomed_hyphenated_alias(self):
        assert resolve_ontology_url("SNOMED-CT:138875005") == resolve_ontology_url(
            "SNOMEDCT:138875005"
        )

    def test_snomedct_non_numeric_local_id_is_none(self):
        assert resolve_ontology_url("SNOMEDCT:ABC123") is None


class TestNativeProviders:
    def test_loinc(self):
        assert resolve_ontology_url("LOINC:8480-6") == "https://loinc.org/8480-6"

    def test_loinc_alternatives(self):
        assert resolve_ontology_url("LOINC:76534-7") == "https://loinc.org/76534-7"
        assert resolve_ontology_url("LOINC:76215-3") == "https://loinc.org/76215-3"

    def test_rxnorm(self):
        url = resolve_ontology_url("RXNORM:5640")
        assert url == "https://mor.nlm.nih.gov/RxNav/search?searchBy=RXCUI&searchTerm=5640"

    def test_rxcui_alias(self):
        assert resolve_ontology_url("RXCUI:5640") == resolve_ontology_url("RXNORM:5640")

    def test_rxnorm_non_numeric_local_id_is_none(self):
        assert resolve_ontology_url("RXNORM:abc") is None

    def test_icd10(self):
        fy = current_icd10cm_fiscal_year()
        url = resolve_ontology_url("ICD10:E11.9")
        assert url == f"https://icd10cmtool.cdc.gov/?fy=FY{fy}&query=E11.9"

    def test_icd10cm_alias(self):
        assert resolve_ontology_url("ICD10CM:E11.9") == resolve_ontology_url("ICD10:E11.9")


class TestFiscalYearHelper:
    def test_september_is_same_calendar_year(self):
        assert current_icd10cm_fiscal_year(date(2026, 9, 10)) == 2026
        assert current_icd10cm_fiscal_year(date(2026, 9, 30)) == 2026

    def test_october_rolls_to_next_fiscal_year(self):
        assert current_icd10cm_fiscal_year(date(2026, 10, 1)) == 2027

    def test_december_stays_in_next_fiscal_year(self):
        assert current_icd10cm_fiscal_year(date(2026, 12, 31)) == 2027

    def test_march_uses_current_fiscal_year(self):
        assert current_icd10cm_fiscal_year(date(2027, 3, 1)) == 2027

    def test_january_uses_current_fiscal_year(self):
        assert current_icd10cm_fiscal_year(date(2027, 1, 1)) == 2027


class TestNormalizationAndEdgeCases:
    def test_lowercase_prefix(self):
        assert resolve_ontology_url("loinc:8480-6") == "https://loinc.org/8480-6"

    def test_surrounding_whitespace(self):
        assert resolve_ontology_url("  LOINC:8480-6  ") == "https://loinc.org/8480-6"

    def test_unsupported_ontology_is_none(self):
        assert resolve_ontology_url("GO:0008150") is None

    def test_malformed_curie_extra_colon_is_none(self):
        assert resolve_ontology_url("SNOMEDCT:123:456") is None

    def test_empty_local_identifier_is_none(self):
        assert resolve_ontology_url("HP:") is None
        assert resolve_ontology_url("LOINC:") is None

    def test_blank_input_is_none(self):
        assert resolve_ontology_url("") is None
        assert resolve_ontology_url("   ") is None

    def test_none_input_is_none(self):
        assert resolve_ontology_url(None) is None  # type: ignore[arg-type]

    def test_unmapped_is_none(self):
        assert resolve_ontology_url("UNMAPPED") is None

    def test_unknown_unmapped_is_none(self):
        assert resolve_ontology_url("UNKNOWN:UNMAPPED") is None

    def test_unmapped_case_insensitive(self):
        assert resolve_ontology_url("unmapped") is None

    def test_bare_loinc_with_hint_resolves(self):
        assert resolve_ontology_url("8480-6", ontology_hint="LOINC") == "https://loinc.org/8480-6"

    def test_bare_loinc_without_hint_is_none(self):
        assert resolve_ontology_url("8480-6") is None

    def test_returned_prefix_overrides_hint(self):
        # Requested ontology EFO, returned code is HP — must resolve to HPO,
        # never let the hint override a prefix that is actually present.
        efo_hp = resolve_ontology_url("HP:0001250", ontology_hint="EFO")
        assert efo_hp == resolve_ontology_url("HP:0001250")
        assert "ontologies/hp/" in efo_hp

    def test_hint_ignored_when_prefix_present_even_if_unsupported(self):
        # A malformed/unsupported prefix present in the code itself must not
        # fall back to a hint — that would be guessing.
        assert resolve_ontology_url("GO:0008150", ontology_hint="LOINC") is None

    def test_no_http_request_performed(self, monkeypatch):
        import httpx
        import requests

        def _fail(*_args, **_kwargs):
            raise AssertionError("resolve_ontology_url must not perform HTTP requests")

        monkeypatch.setattr(requests, "get", _fail)
        monkeypatch.setattr(httpx, "get", _fail)
        for code in (
            "HP:0001250",
            "MONDO:0005180",
            "EFO:0004340",
            "NCIT:C3224",
            "CHEBI:15377",
            "SNOMEDCT:138875005",
            "LOINC:8480-6",
            "ICD10:E11.9",
            "RXNORM:5640",
        ):
            resolve_ontology_url(code)
