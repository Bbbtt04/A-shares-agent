from datetime import timezone
from importlib import import_module

import pytest
from pydantic import ValidationError


def public_contracts():
    return import_module("trading_agent_system.core.contracts")


def test_evidence_reference_accepts_optional_source_and_citation_label():
    EvidenceReference = public_contracts().EvidenceReference

    minimal = EvidenceReference(evidence_id="ev_001")
    detailed = EvidenceReference(
        evidence_id="ev_002",
        source="eastmoney",
        citation_label="EastMoney 2026-06-14",
    )

    assert minimal.evidence_id == "ev_001"
    assert minimal.source is None
    assert minimal.citation_label is None
    assert detailed.source == "eastmoney"
    assert detailed.citation_label == "EastMoney 2026-06-14"


def test_agent_conclusion_separates_kind_confidence_and_evidence():
    contracts = public_contracts()
    AgentConclusion = contracts.AgentConclusion
    EvidenceReference = contracts.EvidenceReference

    evidence = EvidenceReference(evidence_id="ev_001", source="filing")
    conclusion = AgentConclusion(
        kind="fact",
        statement="Revenue increased quarter over quarter.",
        confidence=1.0,
        evidence=[evidence],
    )
    default_evidence = AgentConclusion(
        kind="inference",
        statement="The margin trend may continue.",
        confidence=0.65,
    )

    assert conclusion.kind == "fact"
    assert conclusion.confidence == 1.0
    assert conclusion.evidence == [evidence]
    assert default_evidence.evidence == []


@pytest.mark.parametrize("kind", ["fact", "inference", "view", "risk"])
def test_agent_conclusion_accepts_public_kinds(kind):
    AgentConclusion = public_contracts().AgentConclusion

    conclusion = AgentConclusion(
        kind=kind,
        statement=f"{kind} statement",
        confidence=0.5,
    )

    assert conclusion.kind == kind


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "rumor"),
        ("confidence", -0.01),
        ("confidence", 1.01),
    ],
)
def test_agent_conclusion_rejects_invalid_kind_or_confidence(field, value):
    AgentConclusion = public_contracts().AgentConclusion

    payload = {
        "kind": "fact",
        "statement": "Validated statement.",
        "confidence": 0.5,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentConclusion(**payload)


def test_agent_output_envelope_defaults_identity_time_and_lists():
    AgentOutputEnvelope = public_contracts().AgentOutputEnvelope

    envelope = AgentOutputEnvelope(agent="premarket")

    assert envelope.agent == "premarket"
    assert envelope.run_id is None
    assert envelope.conclusions == []
    assert envelope.evidence_ids == []
    assert envelope.output_id.startswith("agent_output_")
    assert envelope.created_at.tzinfo is timezone.utc


def test_agent_output_envelope_carries_conclusions_and_evidence_ids():
    contracts = public_contracts()
    AgentConclusion = contracts.AgentConclusion
    AgentOutputEnvelope = contracts.AgentOutputEnvelope
    EvidenceReference = contracts.EvidenceReference

    conclusion = AgentConclusion(
        kind="risk",
        statement="Liquidity could dry up near the close.",
        confidence=0.4,
        evidence=[EvidenceReference(evidence_id="ev_liquidity")],
    )

    envelope = AgentOutputEnvelope(
        agent="intraday",
        run_id="run_001",
        conclusions=[conclusion],
        evidence_ids=["ev_liquidity"],
    )

    assert envelope.run_id == "run_001"
    assert envelope.conclusions == [conclusion]
    assert envelope.evidence_ids == ["ev_liquidity"]
