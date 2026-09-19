from typing import Any

from dev_decision.context import ContextPacket
from dev_decision.shared.domain.decisions import validate_response
from dev_decision.shared.domain.inputs import (
    Item,
    attach_context,
    checked_text,
    item_map,
    review_metadata,
    threshold,
)
from dev_decision.shared.ports.jev import JevClient


async def verify(
    claims: list[Item],
    evidence: str,
    auto_accept: float = 0.8,
    *,
    client: JevClient,
    context: ContextPacket | None = None,
) -> dict[str, Any]:
    threshold(auto_accept)
    state = {
        "task": "verify",
        "claims": item_map(claims),
        "evidence": checked_text(evidence, allow_empty=True),
    }
    questions = {
        claim.id: {
            "type": "choice",
            "instructions": f"Usando apenas state.evidence, classifique a claim: {claim.text}",
            "criteria": {
                "supports": "A evidência sustenta a claim.",
                "contradicts": "A evidência contradiz a claim.",
                "unsupported": "A evidência é ausente, insuficiente ou conflitante.",
            },
        }
        for claim in claims
    }
    response = await client.decide(attach_context(state, context), questions)
    validate_response(response, questions)
    names = {
        "supports": "verified",
        "contradicts": "contradicted",
        "unsupported": "unsupported",
    }
    verdicts = []
    for claim in claims:
        answer = response["answers"][claim.id]
        choice = answer["choice"]
        verdicts.append(
            {
                "id": claim.id,
                "verdict": names[choice],
                "confidence": answer["confidence"],
                "probabilities": answer["probabilities"],
                "would_auto_accept": bool(evidence.strip())
                and choice == "supports"
                and answer["confidence"] >= auto_accept
                and answer["probabilities"][choice] >= auto_accept,
            }
        )
    return {
        **review_metadata(client.mode, response),
        "verdicts": verdicts,
        "summary": {
            name: sum(v["verdict"] == name for v in verdicts) for name in names.values()
        },
    }
