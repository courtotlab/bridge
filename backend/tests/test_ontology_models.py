import pytest
from pydantic import ValidationError

from app.models.mapping import SingleMappingRequest
from app.models.session import InputSummary


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ([], None),
        ("LOINC", ["LOINC"]),
        (["LOINC", "HPO"], ["LOINC", "HPO"]),
        (["LOINC", " HPO ", "loinc", ""], ["LOINC", "HPO"]),
        ("Auto-detect", None),
        ("auto", None),
    ],
)
def test_single_mapping_request_normalizes_target_ontologies(raw, expected):
    request = SingleMappingRequest(source_term="sbp", target_ontologies=raw)

    assert request.target_ontologies == expected


def test_single_mapping_request_rejects_non_string_list_items():
    with pytest.raises(ValidationError):
        SingleMappingRequest(source_term="sbp", target_ontologies=["LOINC", 3])


def test_session_input_summary_accepts_canonical_plural_field():
    summary = InputSummary(target_ontologies=["LOINC", "HPO"])

    assert summary.target_ontologies == ["LOINC", "HPO"]
    assert "target_ontology" not in summary.model_dump()


def test_session_input_summary_populates_plural_from_legacy_singular_field():
    summary = InputSummary(target_ontology="LOINC")

    assert summary.target_ontologies == ["LOINC"]
    assert "target_ontology" not in summary.model_dump()


def test_session_input_summary_plural_field_wins_over_legacy_singular_field():
    summary = InputSummary(
        target_ontology="LOINC",
        target_ontologies=["HPO", "MONDO"],
    )

    assert summary.target_ontologies == ["HPO", "MONDO"]


def test_session_input_summary_preserves_multiple_values_as_list():
    summary = InputSummary(target_ontologies=["LOINC", "HPO"])

    assert summary.model_dump()["target_ontologies"] == ["LOINC", "HPO"]
