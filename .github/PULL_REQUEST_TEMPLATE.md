<!--
Research first: link the issue this PR implements (features require an
agreed issue before a PR; drive-by feature PRs are closed without review)
and confirm you searched for existing related issues and PRs.
-->

## Summary

What changed, and why.

## Linked issue

Closes #

## Verification

Exact commands run and their results (required — PRs without verification
results are not reviewed):

```
uv sync --frozen
uv run pytest -q test
uv run bash test/run.sh
uv run python scripts/check_public_tree.py
```

- [ ] `uv run pytest -q test` — (result)
- [ ] `uv run bash test/run.sh` — (result)
- [ ] `uv run python scripts/check_public_tree.py` — (result, when paths changed)

## Scope checklist

- [ ] The change is minimal; no drive-by refactors or reformatting.
- [ ] New staging-only paths (if any) are registered in `dev-only.txt`.
- [ ] Docs, changelog, and i18n READMEs are updated where user-visible behavior changed.
