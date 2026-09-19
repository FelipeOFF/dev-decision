"""Native Claude Code hooks for skill routing and structured decisions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # pragma: no cover - exercised by the installed hook
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_decision.client import ReviewRequest
from dev_decision.codex_client import DecisionFn, mcp_question_decider
from dev_decision.privacy import ensure_safe_content
from dev_decision.routing import confirm_skill_loaded, route_skills
from dev_decision.transport import MCPTransportError

TOKEN_ENV = "DEV_DECISION_MCP_API_KEY"
MAX_INPUT_BYTES = 4 * 1024 * 1024
SkillRouter = Callable[[str, Path, str], Awaitable[dict[str, Any]]]
_ACTIVE: ContextVar[bool] = ContextVar("dev_decision_claude_hook_active", default=False)
_WARNED_SESSIONS: set[str] = set()
_OFFLINE_WARNING = (
    "Dev Decision MCP está indisponível; o Claude Code continuará sem automação."
)


@dataclass(frozen=True)
class ClaudeHookConfig:
    url: str
    skill_roots: tuple[Path, ...] = ()
    sources: tuple[str, ...] = ("AGENTS.md", "CONTEXT.md")
    required: tuple[str, ...] = ()
    timeout_seconds: float = 30
    token_env: str = TOKEN_ENV
    state_root: Path | None = None


def _human_question(warning: str | None = None) -> dict[str, Any]:
    context = (
        "Dev Decision não autorizou uma escolha automática; mantenha "
        "esta pergunta para resposta humana. Origem: human."
    )
    if warning:
        context = f"{warning} {context}"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": context,
        }
    }


def _session_digest(payload: dict[str, Any]) -> str | None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    return hashlib.sha256(session_id.encode()).hexdigest()


def _offline_marker(
    payload: dict[str, Any], config: ClaudeHookConfig
) -> tuple[str | None, Path | None]:
    digest = _session_digest(payload)
    if digest is None or config.state_root is None:
        return digest, None
    return digest, config.state_root.expanduser().resolve() / f"offline-{digest}"


def _offline_known(payload: dict[str, Any], config: ClaudeHookConfig) -> bool:
    digest, marker = _offline_marker(payload, config)
    return (marker is not None and marker.exists()) or (
        marker is None and digest is not None and digest in _WARNED_SESSIONS
    )


def _warning(payload: dict[str, Any], config: ClaudeHookConfig) -> str | None:
    digest, marker = _offline_marker(payload, config)
    if digest is None:
        return _OFFLINE_WARNING
    if config.state_root is None:
        if digest in _WARNED_SESSIONS:
            return None
        _WARNED_SESSIONS.add(digest)
        return _OFFLINE_WARNING
    assert marker is not None
    root = marker.parent
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    try:
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    os.close(descriptor)
    return _OFFLINE_WARNING


def _offline_result(result: dict[str, Any]) -> bool:
    def offline(error: Any) -> bool:
        return isinstance(error, dict) and (
            error.get("fallback") == "harness"
            or error.get("code") in {"connection", "timeout", "transport"}
        )

    if offline(result.get("error")):
        return True
    for evaluation in result.get("evaluations", []):
        if not isinstance(evaluation, dict):
            continue
        evaluation_result = evaluation.get("result")
        if isinstance(evaluation_result, dict) and offline(
            evaluation_result.get("error")
        ):
            return True
    return False


async def _attempt(operation: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    for attempt in range(2):
        try:
            result = await operation()
        except (MCPTransportError, OSError, TimeoutError):
            if attempt == 0:
                continue
            raise
        if not _offline_result(result) or attempt == 1:
            return result
    raise AssertionError("The bounded MCP retry loop must return.")


def _project(payload: dict[str, Any]) -> Path:
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("Claude Code hook event is missing the working directory.")
    return Path(cwd).resolve()


def _roots(config: ClaudeHookConfig, project: Path) -> tuple[Path, ...]:
    roots = [root.expanduser().resolve() for root in config.skill_roots]
    local = (project / ".claude/skills").resolve()
    if local.is_dir() and local not in roots:
        roots.append(local)
    return tuple(root for root in roots if root.is_dir())


async def _route_prompt(
    prompt: str,
    project: Path,
    token: str,
    config: ClaudeHookConfig,
) -> dict[str, Any]:
    roots = _roots(config, project)
    if not roots:
        return {"action": "needs_human", "origin": "review"}
    sources = [source for source in config.sources if (project / source).is_file()]
    request = ReviewRequest(
        objective=prompt,
        tool="jev_find",
        arguments={"query": prompt, "candidates": []},
        sources=sources,
        required=list(config.required),
        skill_roots=[str(root) for root in roots],
    )
    return await route_skills(
        request,
        project,
        config.url,
        token,
        authorized_roots=list(roots),
        timeout_seconds=config.timeout_seconds,
    )


def _selected_context(
    result: dict[str, Any], roots: tuple[Path, ...]
) -> str | None:
    candidate = result.get("candidate")
    if (
        result.get("action") != "auto"
        or result.get("origin") != "automated"
        or result.get("auto_advance") is not True
        or not isinstance(candidate, dict)
    ):
        return None
    skill_id = candidate.get("id")
    revision = candidate.get("revision")
    instructions = candidate.get("instructions")
    if (
        not isinstance(skill_id, str)
        or not skill_id
        or not isinstance(revision, str)
        or not revision
    ):
        return None
    confirmed = confirm_skill_loaded(
        result,
        skill_id,
        revision,
        authorized_roots=list(roots),
    )
    loaded = confirmed.get("candidate")
    if not isinstance(loaded, dict) or loaded.get("loaded") is not True:
        return None
    if not isinstance(instructions, str) or not instructions.strip():
        return None
    ensure_safe_content(instructions)
    return (
        f"Dev Decision selecionou e carregou {skill_id}. Origem: automated. "
        "Siga estas instruções para o pedido atual:\n\n"
        f"{instructions}"
    )


def _question_request(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]] | None:
    if payload.get("tool_name") != "AskUserQuestion":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    questions = tool_input.get("questions")
    if not isinstance(questions, list) or len(questions) != 1:
        return None
    question = questions[0]
    if not isinstance(question, dict):
        return None
    prompt = question.get("question")
    options = question.get("options")
    requires_authorization = question.get(
        "requiresAuthorization", question.get("requires_authorization", False)
    )
    missing_personal_fact = question.get(
        "missingPersonalFact", question.get("missing_personal_fact", False)
    )
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or not isinstance(options, list)
        or len(options) < 2
        or question.get("multiSelect") is not False
        or question.get("isSecret") is True
        or requires_authorization is not False
        or missing_personal_fact is not False
    ):
        return None
    labels: list[str] = []
    decision_options: list[dict[str, str]] = []
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            return None
        label = option.get("label")
        description = option.get("description")
        if not isinstance(label, str) or not label.strip():
            return None
        if description is not None and not isinstance(description, str):
            return None
        labels.append(label)
        text = f"{label} — {description}" if description else label
        decision_options.append({"id": f"option_{index}", "text": text})
    if len(set(labels)) != len(labels):
        return None
    return (
        {
            "objective": prompt,
            "tool": "jev_decide",
            "arguments": {
                "question": prompt,
                "options": decision_options,
                "question_type": "single_choice",
                "requires_authorization": False,
                "missing_personal_fact": False,
            },
            "artifact": prompt,
        },
        labels,
    )


async def handle_claude_hook(
    payload: dict[str, Any],
    config: ClaudeHookConfig,
    *,
    question_decider: DecisionFn | None = None,
    skill_router: SkillRouter | None = None,
) -> dict[str, Any]:
    """Translate one native hook event; every uncertainty retains human control."""
    event = payload.get("hook_event_name")
    if _ACTIVE.get():
        return _human_question() if event == "PreToolUse" else {}
    marker = _ACTIVE.set(True)
    try:
        token = os.environ.get(config.token_env, "")
        if not token:
            warning = _warning(payload, config)
            return (
                _human_question(warning)
                if event == "PreToolUse"
                else {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": warning,
                    }
                }
                if warning
                else {}
            )
        if _offline_known(payload, config):
            return _human_question() if event == "PreToolUse" else {}
        project = _project(payload)
        if event == "UserPromptSubmit":
            prompt = payload.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                return {}
            router = skill_router
            result = await _attempt(
                lambda: (
                    router(prompt, project, token)
                    if router is not None
                    else _route_prompt(prompt, project, token, config)
                )
            )
            if _offline_result(result):
                warning = _warning(payload, config)
                return (
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": warning,
                        }
                    }
                    if warning
                    else {}
                )
            context = _selected_context(result, _roots(config, project))
            return (
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": context,
                    }
                }
                if context is not None
                else {}
            )
        if event != "PreToolUse":
            return {}
        parsed = _question_request(payload)
        if parsed is None:
            return _human_question()
        request, labels = parsed
        decider = question_decider or mcp_question_decider(
            project,
            config.url,
            token,
            sources=[source for source in config.sources if (project / source).is_file()],
            required=config.required,
            timeout_seconds=config.timeout_seconds,
        )
        decision = await _attempt(lambda: decider(request))
        if _offline_result(decision):
            return _human_question(_warning(payload, config))
        selected = decision.get("decision", {}).get("selected_option")
        option_ids = [item["id"] for item in request["arguments"]["options"]]
        if (
            decision.get("action") != "auto"
            or decision.get("origin") != "automated"
            or selected not in option_ids
        ):
            return _human_question()
        label = labels[option_ids.index(selected)]
        questions = payload["tool_input"]["questions"]
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": "Origem: automated.",
                "updatedInput": {
                    "questions": questions,
                    "answers": {questions[0]["question"]: label},
                },
            }
        }
    except Exception as error:  # noqa: BLE001 - hook failures must retain control
        warning = (
            _warning(payload, config)
            if isinstance(error, (MCPTransportError, OSError, TimeoutError))
            else None
        )
        if event == "PreToolUse":
            return _human_question(warning)
        if warning:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": warning,
                }
            }
        return {}
    finally:
        _ACTIVE.reset(marker)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--skill-root", action="append", type=Path, default=[])
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--required", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--token-env", default=TOKEN_ENV)
    parser.add_argument("--state-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        print("{}")
        return
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError
        result = asyncio.run(
            handle_claude_hook(
                payload,
                ClaudeHookConfig(
                    url=args.url,
                    skill_roots=tuple(args.skill_root),
                    sources=tuple(args.source) or ("AGENTS.md", "CONTEXT.md"),
                    required=tuple(args.required),
                    timeout_seconds=args.timeout,
                    token_env=args.token_env,
                    state_root=args.state_root,
                ),
            )
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        result = {}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
