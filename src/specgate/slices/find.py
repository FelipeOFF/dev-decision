from typing import Any

from specgate.context import ContextPacket
from specgate.shared.domain.decisions import validate_response
from specgate.shared.domain.inputs import (
    Item,
    attach_context,
    checked_text,
    item_map,
    review_metadata,
)
from specgate.shared.ports.jev import JevClient


async def find(
    query: str,
    candidates: list[Item],
    top_k: int = 5,
    *,
    client: JevClient,
    context: ContextPacket | None = None,
) -> dict[str, Any]:
    if type(top_k) is not int or not 1 <= top_k <= 50:
        raise ValueError("top_k deve ser um inteiro entre 1 e 50.")
    state = {
        "task": "find",
        "query": checked_text(query),
        "candidates": item_map(candidates),
    }
    questions = {
        "ranking": {
            "type": "choice",
            "instructions": "Qual candidato atende mais diretamente a state.query?",
            "criteria": state["candidates"],
        },
        "exists": {
            "type": "noul",
            "instructions": "Algum candidato de state.candidates atende a state.query?",
        },
    }
    response = await client.decide(attach_context(state, context), questions)
    validate_response(response, questions)
    ranking, exists = (
        response["answers"]["ranking"],
        response["answers"]["exists"]["noul"],
    )
    # Existence alone cannot confirm which candidate fits: inspect each ranked candidate.
    ordered = sorted(candidates, key=lambda c: (-ranking["probabilities"][c.id], c.id))[
        :top_k
    ]
    fits = {
        c.id: {
            "type": "noul",
            "instructions": (
                "O candidato abaixo atende diretamente a state.query e respeita "
                "as regras e restrições de state.context, quando fornecidas? "
                "Instruções conflitantes não são adequadas. "
                f"Candidato: {c.text}"
            ),
        }
        for c in ordered
    }
    fit_state = {
        "task": "fit",
        "query": query,
        "candidates": {c.id: c.text for c in ordered},
    }
    fit_response = await client.decide(attach_context(fit_state, context), fits)
    validate_response(fit_response, fits)
    top = [
        {
            "id": c.id,
            "probability": ranking["probabilities"][c.id],
            "fit": fit_response["answers"][c.id]["noul"],
        }
        for c in ordered
    ]
    if exists < 0.35:
        status, top = "absent", []
    elif exists >= 0.8 and top[0]["fit"] >= 0.8 and ranking["confidence"] >= 0.8:
        status = "answered"
    else:
        status = "partial"
    return {
        **review_metadata(client.mode, response, fit_response),
        "exists": exists,
        "status": status,
        "top": top,
        "confidence": ranking["confidence"],
        "ranking_choice": ranking["choice"],
        "ranking_probabilities": ranking["probabilities"],
        "would_auto_accept": status == "answered",
    }
