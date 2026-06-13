# Workbench Typography

This workbench is local-first and operational. Typography must reinforce that.

## Rules

- Do not load fonts from CDNs, Google Fonts, or any other remote service.
- Prefer local system stacks only.
- Use sans for controls, tables, labels, headings, and primary UI navigation.
- Use mono for file paths, titles derived from paths, tabular signals, chips, and anything that should feel like filesystem or machine output.
- Use serif sparingly for narrative or explanatory copy only: onboarding, lock-state explanation, and other longer editorial text.

## Type Roles

- `--sans`: operational UI voice. This is the default workbench language.
- `--mono`: filesystem/data voice. Use it where the user is reading paths, codecs, sizes, bitrates, or other literal values.
- `--serif`: reflective copy voice. Never use it for file paths, controls, or dense tabular UI.

## Visual Grammar

- File paths should feel like a file browser, not a magazine layout.
- Display hierarchy should come from scale, weight, spacing, and color before it comes from changing font families.
- If a redesign changes typography, check the file-path columns, source input, search input, preview tree, and chips first. Those are the fastest places to spot semantic drift.

## Non-Goals

- No bundled webfont pipeline until there is an explicit repo decision to own one.
- No decorative type swaps that blur operational text roles.
