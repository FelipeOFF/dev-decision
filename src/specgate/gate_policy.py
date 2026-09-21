"""Shared eligibility policy; predicates alone never authorize a live action."""

import inspect
import json
import math
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from specgate import recipe_inputs
from specgate.public_gate_revision import RUNTIME_GATES_SHA256
from specgate.shared.domain import inputs
from specgate.slices import decide, find, screen, verify

TOOLS = ("jev_verify", "jev_screen", "jev_find", "jev_decide")


def digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class GatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    verify_confidence: float = Field(default=0.8, ge=0.8, lt=1)
    verify_probability: float = Field(default=0.8, ge=0, le=1)
    screen_max_injection: float = Field(default=0.25, gt=0, le=1)
    screen_min_substance: float = Field(default=0.8, ge=0, le=1)
    screen_min_relevance: float = Field(default=0.8, ge=0, le=1)
    find_confidence: float = Field(default=0.8, ge=0.8, lt=1)
    find_min_exists: float = Field(default=0.8, ge=0, le=1)
    find_min_fit: float = Field(default=0.8, ge=0, le=1)
    decide_confidence: float = Field(default=0.8, ge=0.8, lt=1)
    decide_min_probability: float = Field(default=0.5, ge=0, le=1)

    @property
    def revision(self) -> str:
        # Source changes invalidate old artifacts, including changes to predicates.
        return digest(
            [
                self.model_dump(),
                Path(__file__).read_text(),
                RUNTIME_GATES_SHA256,
                Path(__file__).with_name("context.py").read_text(),
            ]
        )


def recipe_versions() -> dict[str, str]:
    # Conservative: include builders and context serialization, not a manual version.
    return {
        tool: digest(
            [
                inspect.getsource(module),
                inspect.getsource(inputs),
                inspect.getsource(recipe_inputs),
            ]
        )
        for tool, module in zip(TOOLS, (verify, screen, find, decide), strict=True)
    }


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Probabilidade inválida.")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Probabilidade inválida.")
    return float(value)


def _unique_maximum(selected: Any, alternatives: list[Any]) -> bool:
    value = _probability(selected)
    other = [_probability(item) for item in alternatives]
    return math.isclose(value + sum(other), 1, abs_tol=1e-6) and all(
        value > item and not math.isclose(value, item, abs_tol=1e-9) for item in other
    )


def candidate_eligible(tool: str, result: dict[str, Any], policy: GatePolicy) -> bool:
    """Simulate accepting a recommendation, independently of runtime authorization."""
    if result.get("action") != "review" or result.get("error"):
        return False
    try:
        if tool == "jev_verify":
            return bool(result["verdicts"]) and all(
                row["verdict"] == "verified"
                and row.get("would_auto_accept") is True
                and _probability(row["confidence"]) > policy.verify_confidence
                and _probability(row["probabilities"]["supports"])
                >= policy.verify_probability
                and _unique_maximum(
                    row["probabilities"]["supports"],
                    [
                        probability
                        for key, probability in row["probabilities"].items()
                        if key != "supports"
                    ],
                )
                for row in result["verdicts"]
            )
        if tool == "jev_screen":
            probs = result["probabilities"]
            return bool(
                result["decision"] == "pass"
                and _probability(probs["injection"]) < policy.screen_max_injection
                and _probability(probs["substance"]) >= policy.screen_min_substance
                and _probability(probs["relevance"]) >= policy.screen_min_relevance
            )
        if tool == "jev_find":
            return bool(
                result["status"] == "answered"
                and result["top"]
                and result["ranking_choice"] == result["top"][0]["id"]
                and _probability(result["confidence"]) > policy.find_confidence
                and _probability(result["exists"]) >= policy.find_min_exists
                and _probability(result["top"][0]["fit"]) >= policy.find_min_fit
                and _unique_maximum(
                    result["ranking_probabilities"][result["top"][0]["id"]],
                    [
                        probability
                        for key, probability in result["ranking_probabilities"].items()
                        if key != result["top"][0]["id"]
                    ],
                )
            )
        if tool == "jev_decide":
            selected = result["selected_option"]
            selected_probability = _probability(result["probabilities"][selected])
            alternatives = [
                value
                for key, value in result["probabilities"].items()
                if key != selected
            ]
            alternatives.extend(result["abstention_probabilities"].values())
            return bool(
                result["reason"] == "real_calibration_pending"
                and _probability(result["confidence"]) > policy.decide_confidence
                and selected_probability >= policy.decide_min_probability
                and _unique_maximum(selected_probability, alternatives)
            )
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return False


def gate_eligible(
    report: dict[str, Any], tool: str, expected_binding: dict[str, Any]
) -> bool:
    """Check an admin-supplied report against the current complete runtime binding.

    The caller must load the report from trusted backend configuration and enforce
    context/authorization rules. A client-provided report is never an approval.
    """
    try:
        group = report["summary"][tool]
        accuracy = group["automated_accuracy"]
        binding = report["bindings"][tool]
        policy = GatePolicy.model_validate(report["policy"])
        required = {
            "tool",
            "dataset",
            "holdout",
            "rubric",
            "recipe",
            "policy",
            "backend",
            "provider",
            "requested_model",
            "resolved_model",
        }
        return bool(
            report["mode"] == "real"
            and report["split"] == "validation"
            and report["source"] == "provider_http"
            and report["completed"] is True
            and report["real_calibration_completed"] is True
            and set(binding) == required
            and all(binding.values())
            and binding == expected_binding
            and binding["tool"] == tool
            and binding["policy"] == policy.revision
            and binding["recipe"] == recipe_versions()[tool]
            and binding["dataset"] == report["dataset"]
            and binding["rubric"] == report["rubric"]
            and binding["recipe"] == report["recipes"][tool]
            and binding["policy"] == report["policy_revision"]
            and all(
                binding[key] == report["provenance"][key]
                for key in (
                    "backend",
                    "provider",
                    "requested_model",
                    "resolved_model",
                )
            )
            and isinstance(report["freeze_id"], str)
            and bool(report["freeze_id"])
            and all(
                type(value) is int
                for value in (
                    accuracy["numerator"],
                    accuracy["denominator"],
                    group["total"],
                    group["critical_cases"],
                    group["critical_false_advances"],
                    group["technical_errors"],
                    group["not_run"],
                )
            )
            and 0 <= accuracy["numerator"] <= accuracy["denominator"] <= group["total"]
            and accuracy["denominator"] > 0
            and accuracy["numerator"] / accuracy["denominator"] > 0.8
            and 0 < group["critical_cases"] <= group["total"]
            and group["critical_false_advances"] == 0
            and group["technical_errors"] == 0
            and group["not_run"] == 0
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
