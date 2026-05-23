# Release notes

*Authorship: Agent-written.*

This is an internal guide for keeping versioning, the changelog, and the roadmap
aligned. Keep it local and lightweight until the first GitHub push is ready.

## Versioning

The current package version is `0.7.0a1`, tagged as `v0.7.0-alpha.1`. Earlier
history in `CHANGELOG.md` is still a planning aid rather than a set of real
tags.

Use the smallest version bump that explains the work:

- `0.x.0-alpha.N` for the first real prerelease cut of a completed lane or
  architecture milestone when more polish is expected before the stable tag.
- `0.x.0` for a new lane, major workflow, or major architecture milestone.
- `0.x.y` for fixes, docs, hardening, UI polish, or small additions inside an
  existing lane.
- `0.9.0` marks Canonical Lists and the next product-shape milestone complete.
- `0.9.x` starts minor follow-up tuning and refactor slices.
- `1.0.0` is reserved for the final refactor slice.
- `1.x` starts with refactor stabilization before the dashboard-led UI overhaul.

Only bump `pyproject.toml` and `normal.__version__` when cutting a real release
or prerelease.

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
