# Releasing

Internal-only release policy for the pre-`1.0` phase.

## Current cadence

- Push small stabilisation, UI polish, and tweak work directly to `main`.
- Do not cut a new alpha for every batch of local work.
- Cut a new version only when there is a coherent checkpoint worth signalling.

## Versioning rule of thumb

- Use `0.7.x-alpha.y` style releases only when the cut is materially useful.
- Bump `0.7` to `0.8` when the product surface has meaningfully advanced or changed shape.
- Use another `alpha` only when a distinct testing checkpoint needs to be marked before the next settled release.
- Avoid over-optimising semver fidelity while the product is still pre-`1.0`.

## Practical workflow

1. Let `main` move freely for polish and stabilisation.
2. Tag a new alpha only for meaningful checkpoints.
3. Bump minor when the product feels materially more complete or materially reshaped.
4. Tighten patch/minor discipline later, when releases are meant for broader outside consumption.

## Notes

- Before `1.0.0`, some looseness is expected.
- Clarity matters more than frequency.
- If release notes start to feel noisy, cut less often.
- If testing or external use needs clearer checkpoints, cut more often.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](docs/writing.md).</sub>
