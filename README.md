# Vision App Creator

Foundation workspace for a typed, evidence-first video intelligence application.

## Bootstrap

```sh
/Users/prakashverma/.local/bin/uv python install 3.12
/Users/prakashverma/.local/bin/uv sync
pnpm install --frozen-lockfile
```

## Verify

```sh
uv run python tools/verify.py static
uv run python tools/verify.py contracts
uv run python tools/verify.py component --area fixtures
pnpm --filter @vision-app/web test
pnpm --filter @vision-app/web typecheck
```

Core imports are CPU-only. Install optional dependencies explicitly with `uv sync --extra vision`, `--extra cloud`, or `--extra evals`. Secrets are supplied only through environment variables; none are committed.
