# One-Shot Movie Normalization Logic

Internal companion to `canonical-cross-section-raw-movie-titles.md`.

The high-level concept: treat movie normalization as a local, evidence-based
pass that turns random file, folder, duplicate, and artifact chaos into a
concise downstream shape. The pass should be confident where the library itself
contains enough evidence, and conservative where it would need to invent facts.

## Target Shape

Default output is concise:

```text
Title (Year)/Title (Year).ext
```

When two copies of the same title/year exist, preserve both by adding the
minimum useful local differentiator:

```text
Ace Ventura Pet Detective (1994)/Ace Ventura Pet Detective (1994).mkv
Ace Ventura Pet Detective (1994) 1080p/Ace Ventura Pet Detective (1994) 1080p.mkv
```

The differentiator may come from the movie file or the containing folder. This
matters after a partial cleanup has already renamed the file to concise form
but left technical tokens in the folder.

## Cleanup Rules

- Loose root movies move into concise folders. If the filename lacks a year but
  a sibling `.nfo` has `<title>` and `<year>`, use that local sidecar identity.
  Example: `Se7en ... .mkv` + `Se7en ... .nfo` becomes
  `Se7en (1995)/Se7en (1995).mkv`.
- No-video movie-shaped artifact folders are still part of normalization. If no
  concise target exists, rename the artifact folder. Example:
  `A Few Good Men (1992) [1080p BluRay AC3 x264 ETRG]` becomes
  `A Few Good Men (1992)`.
- If a no-video artifact folder matches an existing concise target and its
  contents do not collide, merge it into the concise folder. If paths collide,
  keep it review-only.
- Metadata-only collection remnants can be deleted when they contain only
  `.nfo`, `.DS_Store`, or AppleDouble `._*` files. Example:
  `The Mummy 1, 2, 3, 4 - Collection 1999-2017 Eng Subs 1080p [H264-mp4]`
  is a delete candidate when only metadata remains.
- Root AppleDouble files are safe delete proposals. Example:
  `._Cleaner.2007.1080p.BluRay.10bit.x265-HazMatt.mkv`.
- Multi-part folders normalize when every video parses to the same title/year
  and each file has a distinct part label. Example:
  `White Mischief ... CD1 ... .mkv` and `... CD2 ... .mkv` become
  `White Mischief (1987) CD1.mkv` and `White Mischief (1987) CD2.mkv` inside
  `White Mischief (1987)/`.

## Review Boundary

Review is not a failure state. It means the preview can be inspected but the
system should not silently invent destructive behavior.

Keep review when:

- duplicate copies cannot be distinguished from local tokens
- artifact-folder merges would overwrite existing entries
- a no-video folder contains substantive extras such as screenshots or subtitle
  packs and no clear merge target
- title/year cannot be recovered from filename, folder, or local sidecar

Canonical examples:

```text
Battle Royale (2000) [Directors CUT 1080p BluRay H.264 AC3 5.1 BADASSMEDIA]
```

This is a no-video folder with screenshots, so it can be renamed or reviewed,
but not automatically deleted as metadata-only junk.

```text
Body Heat (1981) [1080p William HURT Kathleen TURNER H 264 ENG ITA moviesbyrizzo]
```

This contains subtitle packs, so cleanup must avoid treating it like empty
metadata residue.

The direction is clear: normalize aggressively when local evidence is strong,
preserve duplicates with meaningful minimal labels, merge harmless leftovers,
delete only high-confidence junk, and leave the rest visible for review.
