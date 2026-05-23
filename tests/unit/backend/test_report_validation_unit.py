from __future__ import annotations

import pytest

from backend.report_validation import (
    CHECKLISTS,
    _coerce_present,
    _compact_json_or_text,
    _normalize_validation_payload,
    normalize_validation_standard,
)


def test_normalize_validation_standard_accepts_supported_values():
    assert normalize_validation_standard("gri") == "GRI"
    assert normalize_validation_standard(" SASB ") == "SASB"
    assert normalize_validation_standard("tcfd") == "TCFD"


def test_normalize_validation_standard_rejects_unknown_value():
    with pytest.raises(ValueError):
        normalize_validation_standard("ESRS")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("tak", True),
        ("present", True),
        ("no", False),
        (1, True),
        (0, False),
        (None, False),
    ],
)
def test_coerce_present_handles_common_llm_variants(value, expected):
    assert _coerce_present(value) is expected


def test_normalize_validation_payload_recomputes_score_and_fills_missing_items():
    payload = {
        "overall_status": "complete",
        "score": 100,
        "items": [
            {"code": "GRI 305-1", "present": True, "evidence": "Scope 1 present"},
            {"code": "GRI 305-2", "present": "true"},
        ],
        "summary": "",
    }

    result = _normalize_validation_payload(
        payload=payload,
        report_id="r1",
        standard="GRI",
        checklist=CHECKLISTS["GRI"],
    )

    assert result.score == 25
    assert result.overall_status == "partial"
    assert len(result.items) == len(CHECKLISTS["GRI"])
    assert result.items[0].label == CHECKLISTS["GRI"][0]["label"]
    assert "2/8" in result.summary


def test_compact_json_or_text_truncates_serialized_values():
    value = {"long": "x" * 50}

    compact = _compact_json_or_text(value, max_chars=20)

    assert len(compact) == 20
    assert compact.startswith("{")
