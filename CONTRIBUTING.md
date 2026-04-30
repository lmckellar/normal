# Contributing

Contributions are welcome — happy to have them.

## Before opening a PR

- Check the roadmap (`docs/roadmap.md`) — if your change touches a post-v1 area, it may not be in scope yet
- Open an issue first for anything non-trivial so we can agree on approach before you write code

## Running tests

```bash
python3 -m pytest tests/
```

## Code style

- No docstrings or inline comments unless the reason is genuinely non-obvious
- No new dependencies without discussion
- CLI commands are report-only by default; mutations are always opt-in
- Do not relax the safety constraints in `docs/safety.md`
