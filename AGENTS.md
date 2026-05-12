Use concise language.
Do not invent requirements or business logic.
Use the smallest safe default when needed and label it clearly.
Start local and keep documentation lean and internal-only until ready for first push to Github.
Think horizontally and vertically before and during implementation and highlight relevant upstream considerations / impacts / implications.
Do not decompose work into tiny slices by default; prefer the largest safe and coherent implementation slice the target agent can handle reliably.

## Testing

This repo uses `unittest` tests. Run focused tests with `python -m unittest ...` or `.venv/bin/python -m unittest ...`; do not reach for `pytest` unless the repo adds it explicitly.
