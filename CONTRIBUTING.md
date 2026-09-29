# Contributing to Sleeper

Thank you for your interest in Sleeper, a local browser bridge for AI agents.
This guide describes how to report problems and propose changes.

## Research first (mandatory)

Before opening an issue or a pull request, research what already exists:

1. Search the [open issues](https://github.com/shy-tangerine/Sleeper/issues)
   and [pull requests](https://github.com/shy-tangerine/Sleeper/pulls) for
   your topic, including closed items that describe the same root cause.
2. Read the [documentation](docs/commands.md) and the
   [changelog](CHANGELOG.md) — the behavior you are reporting may already be
   fixed on the default branch or documented as intentional.
3. Check the [security policy](SECURITY.md). Anything with a confidentiality
   or integrity impact goes through private vulnerability reporting, never a
   public issue.

Sleeper is agent-facing: many contributors are coding agents, and duplicate
reports waste review capacity for everyone. An issue or PR that duplicates an
open thread will be closed as a duplicate with a link.

## What is welcome

- **Bug reports** — open an issue using the bug report template, with
  reproduction steps and versions (daemon, CLI, add-on, browser).
- **Small fixes** — typo corrections, documentation clarifications, and
  narrowly scoped bug fixes can come directly as a pull request.
- **Features** — open an issue first and agree on the approach before
  writing code. Drive-by feature pull requests are closed without review.

## Workflow

Outside contributors work through the standard fork-and-pull-request flow;
do not ask for, or expect, direct push access. Review and merge decisions
stay with the maintainer.

1. Fork the repository and create your change on top of `main`.
2. Keep the change minimal: no drive-by refactors, no reformatting of
   untouched lines.
3. Run the checks locally and include exact results in the PR description:

   ```bash
   uv sync --frozen
   uv run pytest -q test
   uv run bash test/run.sh
   uv run python scripts/check_public_tree.py
   ```

4. Describe what changed and why; link the issue the change implements.

## No AI-disclosure requirement

Contributors are not required to disclose whether AI tools were used. What
matters is that the change is tested, minimal, and honest about what it does;
you are responsible for everything you submit, human- or AI-written.

## Licensing

By contributing, you agree that your contributions are licensed under the
[MIT license](LICENSE) on the same terms as the rest of the project.
