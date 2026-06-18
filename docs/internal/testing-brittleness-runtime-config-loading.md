# Testing Brittleness: Runtime Config Loading

## Issue Class
Tests fail unpredictably on **unrelated changes** (e.g., README edits) because they depend on **external file state that varies between environments**.

## Pattern
A function under test loads configuration from disk at runtime, and tests don't mock that loading:

```python
def scan_movie_profiles(source_root: Path, ...) -> MovieProfileReport:
    standards = load_movie_standards()  # ← Loads from disk!
    # ... rest of function uses `standards`
```

Tests call this function with minimal fake data:
```python
report = scan_movie_profiles(source, probe_media=lambda path: fake_facts[path])
```

**Result:** Test passes/fails depending on what's on disk:
- **Local dev machine with `movie_standards.json`** → loads user's stricter standards → test fails
- **GitHub Actions CI (clean env)** → loads defaults only → test passes

The loaded config changes test behavior without the test knowing about it.

## Real-World Case
[Commit bf17d1d](https://github.com/lmckellar/normal/commit/bf17d1d) (README edit) broke `test_scan_movie_profiles_assigns_profile_and_percentile`:
- Test expected `playback_risk` in risk_counts
- Got `standards_failure` instead (from stricter loaded standards)
- Failure had nothing to do with the README change

## Solution
**Mock config loading functions** in tests that don't explicitly test config loading:

```python
with patch("normal.movie_profile.load_movie_standards", return_value=DEFAULT_MOVIE_STANDARDS):
    report = scan_movie_profiles(source, probe_media=probe)
```

This ensures:
- ✅ Tests are environment-independent
- ✅ Tests don't depend on filesystem state  
- ✅ Consistent results everywhere

## Functions to Watch For
In `normal/movie_profile.py` and related modules:
- `load_movie_standards()` — loads from disk, can vary per environment
- `load_operator_preferences()` — same issue
- `load_moron_encoders()` — data file loading
- Any function that calls `*.read_text()` or loads JSON from disk at runtime

## Broader Audit
Search for this pattern across the test suite:
1. Find all `load_*()` or config-loading functions
2. Find all tests that call functions using those loaders
3. Check if the test data would pass/fail under different loaded configs
4. If the test doesn't explicitly test config loading, **mock it**

### Example Search
```bash
# Find runtime config loading in the codebase
grep -r "\.read_text()\|json.loads.*\.read_text()" normal/ --include="*.py" | grep -v test

# Find tests that call those functions without mocking
grep -r "scan_movie_profiles\|scan_movie_cleanup" tests/ --include="*.py" | grep -v patch
```

## Fixed Tests (2026-06-19)
- `tests/test_movie_profile.py` (4 tests)
- `tests/test_movie_enriched.py` (1 test)
- `tests/test_movie_title_traits.py` (2 tests)

All now mock `load_movie_standards()` to use defaults consistently.
