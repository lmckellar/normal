# Release notes

This is an internal guide for keeping versioning, the changelog, and the roadmap
aligned. Keep it local and lightweight until the first GitHub push is ready.

## Versioning

The current published package version is still `0.1.0`. The retroactively
rebuilt history in `CHANGELOG.md` is a planning aid, not a set of real tags.

Use the smallest version bump that explains the work:

- `0.x.0` for a new lane, major workflow, or major architecture milestone.
- `0.x.y` for fixes, docs, hardening, UI polish, or small additions inside an
  existing lane.
- `0.9.0` marks Canonical Lists and Music Recommendation lane passes complete.
- `0.9.x` starts minor recommendation tuning and refactor slices.
- `1.0.0` is reserved for the final refactor slice.
- `1.x` starts with refactor stabilization before the dashboard-led UI overhaul.

Do not bump `pyproject.toml` or `normal.__version__` until cutting a real
release.

## Changelog

Write changelog entries for users first and implementation second.

- Keep unreleased work under `[Unreleased]`.
- Move entries into a version section only when that version boundary is clear.
- Do not preserve removed experiments unless they explain a user-visible change.
- Keep known issues concrete and current.

## Roadmap

The roadmap should tell the release story, not list every idea.

- Keep the next few coherent release candidates visible.
- Treat collection intelligence, refactor slices, and the later UI overhaul as
  first-class product milestones.
- Keep lane-sized future work below the architecture milestones unless it must
  happen first.
- Label defaults and assumptions when the implementation is still open.
- Review and update `Where we are now` whenever changelog current-state entries
  change, including `[Unreleased]` work.

## Release cut checklist

- Update `CHANGELOG.md`.
- Review `docs/roadmap.md` and update `Where we are now` for any current-state
  change.
- Bump `pyproject.toml` and `normal/__init__.py` to the release version.
- Run `python3 -m unittest discover -s tests`.
- Create a matching git tag.
