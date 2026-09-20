<h1 align="center">Dev Decision</h1>

<p align="center">
  <em>Coding agents improvise on spec questions. Dev Decision asks Jev and keeps the answer typed.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/works%20with-Codex%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor%20%C2%B7%20Grok%20Build%20%C2%B7%20Grok%20Bot-111111?style=flat-square" alt="Works with Codex, Claude Code, Cursor, Grok Build and Grok Bot">
  <img src="https://img.shields.io/badge/license-MIT-111111?style=flat-square" alt="MIT license">
  <img src="https://img.shields.io/badge/python-3.12%2B-111111?style=flat-square" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux-111111?style=flat-square" alt="macOS and Linux">
</p>

<p align="center">
  <strong>Grill, spec, tickets, implement &middot; one plugin for every harness on the machine &middot; human review until a real gate exists</strong>
</p>

---

```
npx @felipeoff/dev-decision install --host https://YOUR_MCP/mcp
npx @felipeoff/dev-decision doctor --project .
```

Then start `codex`, `claude`, Cursor, `grok` or Grok Bot as usual. That is the whole setup.

macOS or Linux, Python 3.12+. Node 18 is only the bootstrap; the product runtime is Python. The installer detects the harnesses on this machine, asks which ones to wire, and stores the MCP API key in an owner-only file. Never pass the key on the command line.

## What it does

A coding agent can write a spec, open tickets and implement a slice without ever deciding a typed question against project evidence. Grill questions become chat. Acceptance criteria become prose. A "looks good" from the same model that wrote the patch is not a verdict.

Dev Decision is the harness plugin for that gap. It installs skills and a private MCP client into the agents you already use. The harness keeps writing. [Jev](https://docs.typesafe.ai/concepts/system-one), TypeSafe's decision model, answers a typed question about the evidence you authorized: a choice, a claim, a screen, a ranking. The MCP call stays attached to the turn. There is no daemon, no callback later, no merge from a model.

- One install for every harness it finds. `--harness` selects; `--yes` takes all of them.
- Skills ship in English and run the same flow everywhere: `grill-with-jev` → `to-spec-jev` → `to-tickets-jev` → `implement-spec-jev` → `verify-spec-jev`.
- Your MCP host, your API key. Model keys stay on the server. The plugin never logs the credential.
- If the MCP is down, the harness still runs. The decision stays in human review. One warning per session.

Automatic advance stays off until an operator installs a real calibration gate. Mock, replay and contract fixtures do not open it.

## Why a decision model

Asking the same LLM that is writing the code "is this in scope?" returns more prose. You then have to parse it, and you cannot treat the answer as a verdict.

Jev answers a typed question with a structured result. `jev_decide` returns a choice. `jev_verify` returns verified, contradicted or unsupported. `jev_screen` returns injection, substance and relevance. `jev_find` ranks candidates. There is nothing to quote back into the prompt as if it were evidence.

That is what makes it reasonable to put a decision on every grill question, every acceptance criterion and every implement gate, without turning the session into another chat with the author of the patch.

## Three minutes to the first routed skill

1. You need a Dev Decision MCP host (`https://…/mcp`) and an API key for it. The key is not a TypeSafe or OpenRouter key; those live on the server.
2. Run `npx @felipeoff/dev-decision install --host https://YOUR_MCP/mcp`. Pick the harnesses it found, or pass `--yes`. Paste the API key when asked; it is written to `~/.config/dev-decision/credentials/default.key` with mode `0600`.
3. Run `npx @felipeoff/dev-decision doctor --project .` in the repo you will work in. Doctor checks runtime, SemVer handshake, auth and the tool catalog. It does not start a model turn.
4. Open the harness. Use `grill-with-jev` on a real scope question.

A question Jev can close from `CONTEXT.md` and the authorized roots comes back as a typed result. A business choice, an authorization, or a gap after three evidence retries stays with you.

## Agents

| Agent | Install | Where it lands |
| --- | --- | --- |
| Codex | `npx @felipeoff/dev-decision install --harness codex` | `~/.agents/skills`, `~/.local/bin/dev-decision-codex` |
| Claude Code | `npx @felipeoff/dev-decision install --harness claude-code` | `~/.claude/settings.json`, `~/.claude/skills` |
| Cursor | `npx @felipeoff/dev-decision install --harness cursor` | `~/.cursor/skills`, `~/.local/bin/dev-decision-cursor` |
| Grok Build | `npx @felipeoff/dev-decision install --harness grok-build` | `~/.grok/skills`, `~/.local/bin/dev-decision-grok-build` |
| Grok Bot | `npx @felipeoff/dev-decision install --harness grok-bot` | `~/.dev-decision/grok-bot` |

`install` with no `--harness` detects what is on this machine and asks once per agent. Repeat installs keep foreign skills and config they do not own.

Codex uses a controlled app-server client. Claude Code uses native `UserPromptSubmit` and `PreToolUse` hooks. Cursor and Grok Build use ACP. Grok Bot has no public interception contract: after install, copy `~/.dev-decision/grok-bot/dev-decision/GROK_BOT.md` as a private skill and attach the Custom MCP in the product. Doctor reports that limit instead of pretending the roundtrip was tested.

Original binaries stay on `PATH`. Wrappers inject `DEV_DECISION_MCP_API_KEY` into that process only.

## Skills

| Skill | What it does |
| --- | --- |
| `grill-with-jev` | Close the scope. Up to three evaluations per question, each retry with new evidence. |
| `to-spec-jev` | Authorized research and a versioned spec. `jev_verify` covers the claims. |
| `to-tickets-jev` | Vertical ticket graph. One repository per ticket. |
| `implement-spec-jev` | Walk the unblocked frontier in a worktree. |
| `verify-spec-jev` | Last gate: every acceptance criterion against worktree evidence, before a draft PR. |

`verify-spec-jev` does not close issues, merge pull requests or publish packages. Those stay human.

## Commands

| Command | What it does |
| --- | --- |
| `dev-decision install` | Detect harnesses, store the MCP key, install skills and wrappers |
| `dev-decision doctor` | Runtime, handshake, auth and tool catalog, no model turn |
| `dev-decision smoke` | Attached handshake + route + one mock tool. No paid inference |
| `dev-decision update` | Explicit. New venv, previous kept as backup, restore on failure |
| `dev-decision uninstall` | Remove plugin-managed files only |

There is no auto-update. A failed install rolls back every destination in that transaction, including a harness that succeeded before a later one failed.

From a source checkout of this client:

```
PYTHONPATH=src python3 -m dev_decision.public_cli install --host https://YOUR_MCP/mcp
PYTHONPATH=src python3 -m dev_decision.public_cli doctor --project .
```

## Privacy, safety, gates

- The API key is never a flag, never in harness config, never logged. Lookups: the credential file, or `DEV_DECISION_MCP_API_KEY` for local automation (still written only to that file).
- Wrappers live in `~/.local/bin/dev-decision-*`. Profile: `~/.config/dev-decision/profiles/default.json`. Python runtime: `~/.local/share/dev-decision`.
- Context sent to the MCP is the evidence you authorized for that call. Model provider keys never leave the server process.
- The client talks to the host over HTTPS (HTTP only on loopback) and uses the system CAs.
- No MCP, auth failure, or a protocol major mismatch: the harness continues and the decision stays in review.
- `action=auto` is not permission to merge, deploy, or publish. Without an installed calibration manifest the server reports `calibrated=false` and `auto_advance=false`.

## Uninstall

```
npx @felipeoff/dev-decision uninstall
```

Removes the managed profile, credential, wrappers and skills this plugin wrote. Harness config it did not create stays. Delete `~/.local/share/dev-decision` yourself if you also want the venv gone.

## License

The public client (`@felipeoff/dev-decision`, `dev-decision-client`) is [MIT](https://github.com/FelipeOFF/dev-decision/blob/master/LICENSE). The MCP server, prompts, calibration and API-key administration stay in the private host repository.
