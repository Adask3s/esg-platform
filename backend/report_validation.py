from __future__ import annotations

import json
import os
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

ValidationStandard = Literal["GRI", "SASB", "TCFD"]


class ReportValidationRequest(BaseModel):
    standard: str = Field(..., description="Validation standard: GRI, SASB or TCFD")


class ReportValidationItem(BaseModel):
    code: str
    label: str
    present: bool
    evidence: str = ""
    recommendation: str = ""


class ReportValidationResult(BaseModel):
    status: Literal["success"] = "success"
    report_id: str
    standard: ValidationStandard
    overall_status: Literal["complete", "partial", "missing"]
    score: int = Field(ge=0, le=100)
    items: list[ReportValidationItem]
    summary: str


CHECKLISTS: dict[ValidationStandard, list[dict[str, str]]] = {
    "GRI": [
        {"code": "GRI 305-1", "label": "Direct Scope 1 GHG emissions"},
        {"code": "GRI 305-2", "label": "Energy indirect Scope 2 GHG emissions"},
        {"code": "GRI 305-3", "label": "Other indirect Scope 3 GHG emissions"},
        {"code": "GRI 305-4", "label": "GHG emissions intensity"},
        {"code": "GRI 305-5", "label": "Reduction of GHG emissions"},
        {"code": "GRI 401-1", "label": "New employee hires and employee turnover"},
        {"code": "GRI 401-2", "label": "Benefits for full-time employees"},
        {"code": "GRI 401-3", "label": "Parental leave"},
    ],
    "SASB": [
        {"code": "IF-EN-160a.1", "label": "Environmental permit and regulation non-compliance incidents"},
        {"code": "IF-EN-160a.2", "label": "Environmental risk management in project design, siting and construction"},
        {"code": "IF-EN-250a.1", "label": "Defect- and safety-related rework costs"},
        {"code": "IF-EN-250a.2", "label": "Legal losses from defect- and safety-related incidents"},
        {"code": "IF-EN-320a.1", "label": "TRIR and fatality rate for direct and contract employees"},
        {"code": "IF-EN-410a.1", "label": "Certified sustainable projects and active projects seeking certification"},
        {"code": "IF-EN-410a.2", "label": "Operational energy and water efficiency in project planning and design"},
        {"code": "IF-EN-410b.1", "label": "Backlog for hydrocarbon-related and renewable energy projects"},
        {"code": "IF-EN-510a.1", "label": "Projects and backlog in high-corruption-risk countries"},
    ],
    "TCFD": [
        {"code": "TCFD Governance a", "label": "Board oversight of climate-related risks and opportunities"},
        {"code": "TCFD Governance b", "label": "Management role in climate-related risk assessment and management"},
        {"code": "TCFD Strategy a", "label": "Climate-related risks and opportunities over short, medium and long term"},
        {"code": "TCFD Strategy b", "label": "Impact on business, strategy and financial planning"},
        {"code": "TCFD Strategy c", "label": "Strategy resilience under climate scenarios"},
        {"code": "TCFD Risk Management a", "label": "Processes for identifying and assessing climate-related risks"},
        {"code": "TCFD Risk Management b", "label": "Processes for managing climate-related risks"},
        {"code": "TCFD Risk Management c", "label": "Integration into overall risk management"},
        {"code": "TCFD Metrics and Targets a", "label": "Metrics used for climate-related risks and opportunities"},
        {"code": "TCFD Metrics and Targets b", "label": "Scope 1, Scope 2 and relevant Scope 3 GHG emissions"},
        {"code": "TCFD Metrics and Targets c", "label": "Targets and performance against targets"},
    ],
}


def normalize_validation_standard(raw_standard: str) -> ValidationStandard:
    standard = (raw_standard or "").strip().upper()
    if standard not in CHECKLISTS:
        raise ValueError("Unsupported validation standard. Use GRI, SASB or TCFD.")
    return standard  # type: ignore[return-value]


def validate_report_content(
    *,
    report_id: str,
    standard: ValidationStandard,
    report_content: dict[str, Any],
    used_chunks: Any = None,
) -> ReportValidationResult:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError("Brak poprawnego OPENAI_API_KEY")

    checklist = CHECKLISTS[standard]
    prompt = _build_validation_prompt(
        standard=standard,
        checklist=checklist,
        report_content=report_content,
        used_chunks=used_chunks,
    )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an ESG reporting assurance analyst. Return only valid JSON. "
                    "Write evidence, recommendations and summary in Polish."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=60.0,
    )

    raw_response = response.choices[0].message.content or "{}"
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI returned invalid JSON: {exc}") from exc

    return _normalize_validation_payload(
        payload=payload,
        report_id=report_id,
        standard=standard,
        checklist=checklist,
    )


def _build_validation_prompt(
    *,
    standard: ValidationStandard,
    checklist: list[dict[str, str]],
    report_content: dict[str, Any],
    used_chunks: Any,
) -> str:
    source_excerpt = _compact_json_or_text(used_chunks, max_chars=9000)
    report_excerpt = _compact_json_or_text(report_content, max_chars=14000)
    checklist_json = json.dumps(checklist, ensure_ascii=False, indent=2)

    return f"""
Validate the generated ESG report against the selected disclosure checklist.

Selected standard: {standard}
Checklist:
{checklist_json}

Rules:
1. Mark an item as present only when the report content contains a concrete disclosure for that checklist code.
2. Evidence must be a short Polish paraphrase or short excerpt from the report/source data.
3. If an item is missing, set present=false and write a concrete Polish recommendation.
4. Do not invent data. Legal or standard context can explain requirements, but it cannot count as company evidence.
5. Return exactly this JSON shape:
{{
  "overall_status": "complete | partial | missing",
  "score": 0,
  "items": [
    {{
      "code": "checklist code",
      "label": "checklist label",
      "present": true,
      "evidence": "Polish evidence",
      "recommendation": "Polish recommendation"
    }}
  ],
  "summary": "Polish summary"
}}

Report JSON:
{report_excerpt}

Source chunks:
{source_excerpt}
"""


def _compact_json_or_text(value: Any, *, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            text = str(value)
    return text[:max_chars]


def _normalize_validation_payload(
    *,
    payload: dict[str, Any],
    report_id: str,
    standard: ValidationStandard,
    checklist: list[dict[str, str]],
) -> ReportValidationResult:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = []

    raw_by_code = {
        str(item.get("code", "")).strip(): item
        for item in raw_items
        if isinstance(item, dict)
    }

    items: list[ReportValidationItem] = []
    for expected in checklist:
        raw_item = raw_by_code.get(expected["code"], {})
        present = _coerce_present(raw_item.get("present")) if isinstance(raw_item, dict) else False
        items.append(
            ReportValidationItem(
                code=expected["code"],
                label=str(raw_item.get("label") or expected["label"]) if isinstance(raw_item, dict) else expected["label"],
                present=present,
                evidence=str(raw_item.get("evidence") or "") if isinstance(raw_item, dict) else "",
                recommendation=str(raw_item.get("recommendation") or "") if isinstance(raw_item, dict) else "",
            )
        )

    present_count = sum(1 for item in items if item.present)
    computed_score = round((present_count / len(items)) * 100) if items else 0
    score = computed_score
    overall_status = "complete" if score == 100 else "missing" if score == 0 else "partial"

    summary = str(payload.get("summary") or "")
    if not summary:
        summary = f"Walidacja {standard}: {present_count}/{len(items)} kryteriow obecnych w raporcie."

    return ReportValidationResult(
        report_id=str(report_id),
        standard=standard,
        overall_status=overall_status,
        score=score,
        items=items,
        summary=summary,
    )

def _coerce_present(raw_present: Any) -> bool:
    if isinstance(raw_present, bool):
        return raw_present
    if isinstance(raw_present, str):
        return raw_present.strip().lower() in {"true", "yes", "tak", "1", "present", "obecne"}
    if isinstance(raw_present, (int, float)):
        return raw_present > 0
    return False
