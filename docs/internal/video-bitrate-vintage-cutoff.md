# Plan: `video_bitrate_vintage_cutoff` for Quality Stances

## Context

Pre-2000 4K content (especially films from the analogue grain era) regularly lands in Library Grade instead of Collector Grade because its video bitrate falls slightly below the 18,000 kbps 4K floor — not due to a bad encode, but because older stock doesn't demand high bitrates. The existing `audio_channels_vintage_cutoff` mechanism already exempts old films from the surround-sound channel requirement. This feature adds a parallel `video_bitrate_vintage_cutoff` that, when a film's release year is below the configured threshold, applies a lower 4K video floor (a separate configurable value: `video_bitrate_vintage_floor_2160p`) instead of the standard one.

Only 4K (2160p) is in scope — 1080p vintage encodes are not a meaningful pattern.

---

## Implementation

All changes are in **`normal/movie_profile.py`**.

### 1. Add field definitions to `build_movie_profile_definitions`

After the existing `audio_channels_atmos_cutoff` field block (around line 444), add two new fields for `collector_grade` (and any other stance where it makes sense — add them to all stances for consistency, let users configure per-stance):

```python
{
    "key": "video_bitrate_vintage_cutoff",
    "label": "Exempt pre-era 4K films from full video bitrate floor",
    "type": "select",
    "value": int(stance.get("video_bitrate_vintage_cutoff", 0)),
    "options": [
        {"value": 0, "label": "Off — apply full floor to all 4K films"},
        {"value": 1980, "label": "Pre-1980 films exempt"},
        {"value": 1990, "label": "Pre-1990 films exempt"},
        {"value": 1995, "label": "Pre-1995 films exempt"},
        {"value": 2000, "label": "Pre-2000 films exempt"},
        {"value": 2005, "label": "Pre-2005 films exempt"},
    ],
},
{
    "key": "video_bitrate_vintage_floor_2160p",
    "label": "Reduced 4K floor for vintage films (kbps)",
    "type": "select",
    "value": int(stance.get("video_bitrate_vintage_floor_2160p", 0)),
    "options": [
        {"value": 0, "label": "Off"},
        {"value": 10000, "label": "10,000 kbps"},
        {"value": 12000, "label": "12,000 kbps"},
        {"value": 14000, "label": "14,000 kbps"},
        {"value": 15000, "label": "15,000 kbps"},
        {"value": 16000, "label": "16,000 kbps"},
    ],
},
```

### 2. Persist new fields in `update_movie_profile_definition` (~line 557)

After the existing `atmos_raw` block, add:

```python
vint_raw = values.get("video_bitrate_vintage_cutoff")
stance["video_bitrate_vintage_cutoff"] = int(vint_raw) if vint_raw is not None and str(vint_raw).isdigit() else 0
vfloor_raw = values.get("video_bitrate_vintage_floor_2160p")
stance["video_bitrate_vintage_floor_2160p"] = int(vfloor_raw) if vfloor_raw is not None and str(vfloor_raw).isdigit() else 0
```

### 3. Apply the exemption in `movie_matches_quality_stance` (~line 934)

Currently:
```python
required_video = resolve_stance_video_floor(label, stance, standards, resolution)
if required_video and (facts.video_bitrate_kbps or 0) < required_video:
    return False
```

Replace with:
```python
required_video = resolve_stance_video_floor(label, stance, standards, resolution)
if required_video and (facts.video_bitrate_kbps or 0) < required_video:
    vintage_cutoff = int(stance.get("video_bitrate_vintage_cutoff") or 0)
    vintage_floor = int(stance.get("video_bitrate_vintage_floor_2160p") or 0)
    exempt = False
    if vintage_cutoff and vintage_floor and resolution == "2160p":
        parsed_identity = parse_movie_name(path)
        year = parsed_identity.year
        if year and year < vintage_cutoff:
            if (facts.video_bitrate_kbps or 0) >= vintage_floor:
                exempt = True
    if not exempt:
        return False
```

---

## Critical files

- `normal/movie_profile.py` — all changes here
  - `build_movie_profile_definitions` (~line 343): add field definitions
  - `update_movie_profile_definition` (~line 530): persist new keys
  - `movie_matches_quality_stance` (~line 925): apply exemption logic

---

## Verification

1. Start the web server, open the movie Library tab
2. Open Quality Profile Inspector for `collector_grade`
3. Confirm the two new fields appear: "Exempt pre-era 4K films..." and "Reduced 4K floor..."
4. Set `video_bitrate_vintage_cutoff` to 2000 and `video_bitrate_vintage_floor_2160p` to 14000, save
5. Re-profile — Phantom Menace (1999, 17,086 kbps) should now classify as Collector Grade
6. Verify a 2001 film at the same bitrate does NOT get the exemption
7. Verify a pre-2000 film at e.g. 9,000 kbps (below the vintage floor) still fails Collector Grade
