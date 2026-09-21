"""Validation at the boundary between a decision provider and its consumers."""

import json
from hashlib import sha256
from typing import Any

from specgate.shared.domain.inputs import Item


def question_revision(
    question: str,
    options: list[Item],
    *,
    question_type: str = "single_choice",
    requires_authorization: bool = False,
    missing_personal_fact: bool = False,
) -> str:
    """Bind a decision to its ordered public options and human-only restrictions."""
    state = {
        "question": question,
        "options": [item.model_dump() for item in options],
        "question_type": question_type,
        "requires_authorization": requires_authorization,
        "missing_personal_fact": missing_personal_fact,
    }
    return sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _require_number(value: Any, maximum: int = 1) -> None:
    if type(value) not in (int, float) or not 0 <= value <= maximum:
        raise ValueError("Resposta do Jev contém um número inválido ou fora da faixa.")


def validate_response(response: dict[str, Any], questions: dict[str, Any]) -> None:
    """Require the decision fields our gates need, preserving provider IDs.

    OpenRouter makes confidence/probabilities optional in its schema. Our gates
    require both for choice/score rather than inventing defaults when absent.
    Request construction is responsible for validating questions beforehand.
    """
    answers = response.get("answers")
    if not isinstance(answers, dict) or answers.keys() != questions.keys():
        raise ValueError("Respostas do Jev não correspondem às perguntas enviadas.")

    for question_id, question in questions.items():
        answer = answers[question_id]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise ValueError("Resposta do Jev possui tipo inesperado.")
        if kind == "noul":
            _require_number(answer.get("noul"))
            continue
        if kind == "choice":
            options = set(question["criteria"])
            choice = answer.get("choice")
            if not isinstance(choice, str) or choice not in options:
                raise ValueError("Jev retornou uma opção não oferecida.")
        elif kind == "score":
            options = {str(index) for index in range(len(question["criteria"]))}
            _require_number(answer.get("score"), len(options) - 1)
        else:
            raise ValueError("Tipo de pergunta Jev não suportado.")

        _require_number(answer.get("confidence"))
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or probabilities.keys() != options:
            raise ValueError("Distribuição do Jev não corresponde às opções enviadas.")
        for probability in probabilities.values():
            _require_number(probability)
