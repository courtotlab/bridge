import csv
import io

from app.models.mapping import AlternativeResult, BatchRowResult
from app.utils.batch_export import build_batch_rows_csv


def _read(csv_text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return reader.fieldnames or [], list(reader)


def _row(**overrides) -> BatchRowResult:
    data = {
        "row_index": 0,
        "field_name": "sbp",
        "label": "Systolic blood pressure",
        "source_description": "Measured at rest",
        "original_row": {
            "source_variable": "sbp",
            "source_label": "Systolic blood pressure",
            "source_description": "Measured at rest",
            "target_ontology": "LOINC",
            "notes from upload": "keep me",
        },
        "original_columns": [
            "source_variable",
            "source_label",
            "source_description",
            "target_ontology",
            "notes from upload",
        ],
        "requested_target_ontology": "LOINC",
        "suggested_code": "LOINC:8480-6",
        "suggested_term": "Systolic blood pressure",
        "ontology": "LOINC",
        "confidence": 0.92,
        "logic_type": "rag",
        "decision": "accepted",
        "notes": "Selected because the label matches.",
        "alternatives": [],
    }
    data.update(overrides)
    return BatchRowResult(**data)


def test_enriched_export_preserves_original_columns_and_appends_mapping_fields():
    headers, rows = _read(build_batch_rows_csv([_row()]))

    assert headers[:5] == [
        "source_variable",
        "source_label",
        "source_description",
        "target_ontology",
        "notes from upload",
    ]
    row = rows[0]
    assert row["source_variable"] == "sbp"
    assert row["source_description"] == "Measured at rest"
    assert row["target_ontology"] == "LOINC"
    assert row["mapped_code"] == "LOINC:8480-6"
    assert row["mapped_term"] == "Systolic blood pressure"
    assert row["mapped_ontology"] == "LOINC"
    assert row["confidence"] == "92%"
    assert row["logic_type"] == "rag"
    assert row["suggested_explanation"] == "Selected because the label matches."
    assert row["decision"] == "accepted"


def test_enriched_export_keeps_values_associated_with_row_index_for_duplicates():
    first = _row(
        row_index=0,
        field_name="dup",
        original_row={"source_variable": "dup", "visit": "baseline"},
        original_columns=["source_variable", "visit"],
        suggested_code="HP:1",
    )
    second = _row(
        row_index=1,
        field_name="dup",
        original_row={"source_variable": "dup", "visit": "follow-up"},
        original_columns=["source_variable", "visit"],
        suggested_code="HP:2",
    )

    _, rows = _read(build_batch_rows_csv([first, second]))

    assert [(row["visit"], row["mapped_code"]) for row in rows] == [
        ("baseline", "HP:1"),
        ("follow-up", "HP:2"),
    ]


def test_enriched_export_distinguishes_requested_and_mapped_ontology_without_source_column():
    row = _row(
        original_row={"source_variable": "ad"},
        original_columns=["source_variable"],
        requested_target_ontology="EFO",
        suggested_code="MONDO:0004975",
        suggested_term="Alzheimer disease",
        ontology="MONDO",
    )

    headers, rows = _read(build_batch_rows_csv([row]))

    assert headers[:3] == ["source_variable", "target_ontology", "mapped_code"]
    assert rows[0]["target_ontology"] == "EFO"
    assert rows[0]["mapped_ontology"] == "MONDO"


def test_enriched_export_flattens_alternatives_with_matching_explanations_and_blanks():
    row = _row(
        alternatives=[
            AlternativeResult(
                code="LOINC:8462-4",
                term="Diastolic blood pressure",
                ontology="LOINC",
                confidence=0.66,
                explanation="Use if the field is diastolic.",
            ),
            AlternativeResult(
                code="HP:0000822",
                term="Hypertension",
                ontology="HPO",
                confidence=0.42,
                explanation="Use if the field stores a diagnosis.",
            ),
        ]
    )

    _, rows = _read(build_batch_rows_csv([row]))
    exported = rows[0]

    assert exported["alternative_1_code"] == "LOINC:8462-4"
    assert exported["alternative_1_term"] == "Diastolic blood pressure"
    assert exported["alternative_1_confidence"] == "66%"
    assert exported["alternative_1_explanation"] == "Use if the field is diastolic."
    assert exported["alternative_2_code"] == "HP:0000822"
    assert exported["alternative_2_explanation"] == "Use if the field stores a diagnosis."
    assert exported["alternative_3_code"] == ""
    assert exported["alternative_5_explanation"] == ""


def test_enriched_export_handles_zero_and_maximum_alternatives():
    alternatives = [
        AlternativeResult(
            code=f"HP:{index}",
            term=f"Term {index}",
            ontology="HPO",
            confidence=0.5,
            explanation=f"Reason {index}",
        )
        for index in range(1, 6)
    ]

    _, rows = _read(build_batch_rows_csv([_row(), _row(alternatives=alternatives)]))

    assert rows[0]["alternative_1_code"] == ""
    assert rows[1]["alternative_5_code"] == "HP:5"
    assert rows[1]["alternative_5_explanation"] == "Reason 5"


def test_enriched_export_escapes_csv_values_and_preserves_unicode_and_blanks():
    row = _row(
        original_row={
            "source_variable": "bp,sys",
            "source_label": 'Systolic "BP"',
            "source_description": "Line 1\nLine 2 µ",
            "blank": "",
        },
        original_columns=[
            "source_variable",
            "source_label",
            "source_description",
            "blank",
        ],
        notes='Reason with comma, quote ", newline\nand unicode µ',
    )

    _, rows = _read(build_batch_rows_csv([row]))

    assert rows[0]["source_variable"] == "bp,sys"
    assert rows[0]["source_label"] == 'Systolic "BP"'
    assert rows[0]["source_description"] == "Line 1\nLine 2 µ"
    assert rows[0]["blank"] == ""
    assert rows[0]["suggested_explanation"] == 'Reason with comma, quote ", newline\nand unicode µ'


def test_enriched_export_prefixes_generated_columns_that_collide_with_source_columns():
    row = _row(
        original_row={
            "confidence": "source-confidence",
            "decision": "source-decision",
            "mapped_code": "source-code",
            "suggested_explanation": "source-explanation",
            "alternative_1_code": "source-alt",
        },
        original_columns=[
            "confidence",
            "decision",
            "mapped_code",
            "suggested_explanation",
            "alternative_1_code",
        ],
    )

    headers, rows = _read(build_batch_rows_csv([row]))
    exported = rows[0]

    assert "confidence" in headers
    assert "bridge_confidence" in headers
    assert exported["confidence"] == "source-confidence"
    assert exported["bridge_confidence"] == "92%"
    assert exported["decision"] == "source-decision"
    assert exported["bridge_decision"] == "accepted"
    assert exported["mapped_code"] == "source-code"
    assert exported["bridge_mapped_code"] == "LOINC:8480-6"
    assert exported["suggested_explanation"] == "source-explanation"
    assert exported["bridge_suggested_explanation"] == "Selected because the label matches."
    assert exported["alternative_1_code"] == "source-alt"
    assert exported["bridge_alternative_1_code"] == ""


def test_enriched_export_supports_unmapped_explanations_and_legacy_rows():
    unmapped = _row(
        suggested_code="UNMAPPED",
        suggested_term="UNMAPPED",
        ontology="",
        confidence=0,
        decision="rejected",
        notes="None of the candidates matched.",
    )
    legacy = BatchRowResult(
        row_index=1,
        field_name="legacy",
        label="Legacy label",
        suggested_code="HP:0001250",
        suggested_term="Seizure",
        ontology="HPO",
        confidence=0.75,
        logic_type="rag",
        decision="pending",
        alternatives=[],
    )

    headers, rows = _read(build_batch_rows_csv([unmapped, legacy]))

    assert "field_name" in headers
    assert rows[0]["suggested_explanation"] == "None of the candidates matched."
    assert rows[1]["field_name"] == "legacy"
    assert rows[1]["label"] == "Legacy label"
    assert rows[1]["mapped_code"] == "HP:0001250"
