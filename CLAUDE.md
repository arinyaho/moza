# CLAUDE.md

Guidance for AI coding agents working in this repository.

## What this is

`moza` routes credentials for people who hold several identities at once — personal, employer, client — across Google, GitHub, Slack, Atlassian, Notion, AWS, and OCI. It ships as a CLI and as an agent skill (`plugins/moza/skills/moza/`).

## Commands

```bash
uv run pytest            # full suite; fast, no network
uv run moza <cmd>        # run the CLI from source
uv run moza doctor       # check local config and backend health
```

## Invariants

**Activation is stateless.** Agent harnesses start a fresh shell for every command, so environment set by `eval "$(moza use <profile>)"` is gone by the next call — silently, with no error. Any code path or documentation that assumes a profile is still active from an earlier invocation is a bug. Prefer `moza exec <profile> -- <cmd>`, or pass the profile explicitly. `eval` is correct only for an interactive human shell, or within a single invocation.

**Wrong identity is the failure mode that matters.** This tool does not crash when it misroutes; it succeeds as the wrong person. Prefer designs that fail loudly over designs that fall back to a default.

**Secrets never reach argv, history, or a transcript.** Read them through the hidden prompt, `--secret-cmd` (which stores a reference, not a value), or stdin. When a token must reach a command, expand it at execution time rather than pasting a literal. Never print a resolved secret to stdout.

**No real-world identifiers in the repository.** No employer or client names, no personal email addresses, no project IDs, no secret names — in code, tests, fixtures, docs, or commit messages. This repository is public, and profile names in examples are drawn from the user's actual working life. Use neutral placeholders (`personal`, `work`, `example.com`).

**Configuration comes from the user's own config, never from a checked-out repository.** A cloned repository must not be able to influence which identity acts on the machine.

## Git

Never push to `main`. Branch, then open a PR. Keep PRs small unless several changes serve one coherent goal.

## Design and planning

Design documents, the roadmap, and the issue tracker live in Notion, not in this repository — the `docs/` directory was removed deliberately. Access is limited to the maintainer; if you cannot reach it, ask rather than reconstructing it here.

- Design overview, architecture, and security considerations — the `moza` page
- `Issues` — the work tracker, one row per unit of work with the reasoning behind it
- `[note] moza-competitive-positioning` — prior-art survey, what is genuinely unserved, and landing-page research

Consult the tracker before starting work, and record decisions there rather than in this file.
