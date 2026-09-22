---
name: iterate-with-jev
description: Judge a maintainer `/iterate` comment on a recurring agent pull request with jev_verify before editing or pushing. Use when that comment arrives, or when installing the loop that accepts it.
---

# Iterate with Jev

Use this when a maintainer comments `/iterate <feedback>` on a pull request
of a recurring agent workflow, or when you are installing that workflow.

The loop is a repo-local skill, a workflow, a memory file, and one open pull
request. The pull request footer tells the maintainer to comment
`/iterate <feedback>`. This skill judges that comment. It does not replace
`grill-with-jev`, `to-spec-jev`, `to-tickets-jev`, `implement-spec-jev`, or
`verify-spec-jev`.

## Before any edit

Read the comment, the current diff, and the memory file. Do not send secrets
or harness transcripts.

Call `jev_verify` with two claims:

- `{pr}:iterate-change` — the feedback fits this diff.
- `{pr}:iterate-memory` — the feedback is a durable rule, not a one-off.

Evidence is the comment, a diff summary, and the current memory file.

## Verdicts

- `verified` on `iterate-change`: edit the pull request branch. Push only
  those edits.
- `verified` on `iterate-memory`: update the memory file. Keep it concise.
  Do not paste a transcript. Push only that file.
- A claim that is not `verified` does not move. That includes
  `auto_advance` false, mock, uncalibrated, contradicted, unsupported, and
  an error. Comment that verdict. If neither claim is `verified`, do not
  push.

If Specgate MCP is unavailable, stop and say the iteration stays in review.
Do not invent a verdict.

Do not merge, deploy, or close the pull request.
