# Release notes

An internal guide for keeping versioning, the changelog, and the roadmap aligned. Lightweight and local until a release is ready to push.

## Versioning

The current package version is `0.7.0a7`, tagged `v0.7.0-alpha.7` and published as a GitHub **prerelease**. Earlier history in `CHANGELOG.md` is a planning aid — reconstructed, not a set of real tags or releases.

Use the smallest bump that explains the work:

- `0.x.0-alpha.N` — first real prerelease cut of a completed lane or architecture milestone, when more polish is expected before the stable tag
- `0.x.0` — a new lane, major workflow, or major architecture milestone
- `0.x.y` — fixes, docs, hardening, UI polish, or small additions inside an existing lane
- `0.9.0` — marks Canonical Lists and the next product-shape milestone complete
- `0.9.x` — minor follow-up tuning and refactor slices
- `1.0.0` — reserved for the final refactor slice
- `1.x` — refactor stabilization before the dashboard-led UI overhaul

Only bump `pyproject.toml` and `normal.__version__` when cutting a real release. Here, **real release** means all four of: a version bump, a changelog section, a matching git tag, and a matching GitHub release object.

## Changelog

Write entries users-first, implementation-second.

- Keep unreleased work under `[Unreleased]`.
- Promote entries into a version section only once that boundary is clear.
- Don't preserve removed experiments unless they explain a user-visible change.
- Keep known issues concrete and current.

## Roadmap

The roadmap tells the release story — it is not a dumping ground for every idea.

- Keep the next few coherent release candidates visible.
- Treat collection intelligence, refactor slices, and the later UI overhaul as first-class milestones.
- Keep lane-sized future work below the architecture milestones unless it must happen first.
- Label defaults and assumptions while the implementation is still open.
- Review **Where we are now** whenever changelog current-state entries change (including `[Unreleased]`): prune resolved concerns, reshuffle by priority, and keep it a short status note rather than a second changelog.

## Release-cut checklist

1. Update `CHANGELOG.md`.
2. Update **Where we are now** in `docs/roadmap.md` for any current-state change.
3. Bump `pyproject.toml` and `normal/__init__.py` to the release version.
4. Run `python3 -m unittest discover -s tests`.
5. Create and push the matching git tag.
6. Publish the matching GitHub release from that tag, marked as a prerelease for `alpha`-class cuts.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
