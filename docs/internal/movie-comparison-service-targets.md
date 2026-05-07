# Movie Comparison Service Targets

Status: working note  
Last reviewed: 2026-05-07

## Goal

Define the initial streaming-service dataset targets for the `Movies > Streaming Service Comparison Dashboard`.

This note is intentionally separate from the live dataset loader. It is the shortlist we should build snapshots for, not a statement that those snapshots already exist.

## Recommended default basis

These are the core general-interest U.S. subscription services worth treating as the default comparison basis:

| Dataset ID | Display name | Why it belongs in phase 1 |
|---|---|---|
| `prime_video_snapshot` | Prime Video | Top-tier scale and broad licensed/original movie footprint |
| `netflix_snapshot` | Netflix | Top-tier scale and strong original/exclusive movie signal |
| `disney_plus_snapshot` | Disney+ | Major mainstream catalogue with durable franchise pull |
| `hulu_snapshot` | Hulu | Still distinct enough to track separately despite Disney convergence |
| `max_snapshot` | Max | Major studio catalogue and prestige overlap anchor |
| `apple_tv_plus_snapshot` | Apple TV+ | Smaller library but outsized prestige/original signal |
| `paramount_plus_snapshot` | Paramount+ | Large mainstream studio/service dataset worth tracking |

## Not part of the default basis

These should stay out of the initial comparison basis unless we decide to support a separate mode:

- `Peacock`
- FAST services like `Tubi`, `Pluto TV`, and `The Roku Channel`
- live TV bundles like `YouTube TV`, `Sling`, `Fubo`, and `DirecTV Stream`
- bundle SKUs like `Disney+, Hulu, Max Bundle`
- storefront/channel add-ons that are not clean standalone catalogues in practice
- niche film services like `Criterion Channel`, `Mubi`, `AMC+`, `MGM+`, and `Shudder`

## Upstream implications

- Keep `Disney+` and `Hulu` as separate datasets even though Disney is tightening the product/app story in 2026. Their catalogues and overlap value are still analytically different.
- Keep `Max` as the dataset display name. Some research sources still label the service `HBO Max`, but the official consumer product remains `Max`/`max.com`.
- Avoid using bundle products as datasets. The dashboard compares title overlap against catalogue snapshots; bundles blur ownership and inflate union overlap.
- FAST catalogues churn too quickly for the current local-snapshot workflow to be a stable baseline.
- `Apple TV+` is worth keeping despite a smaller library because the dashboard already separates service overlap from prestige overlap; that makes a prestige-heavy service still informative.

## Current market context used for this shortlist

As of 2026-05-07, the best default basis is the reduced large-provider U.S. subscription-video set above.

- JustWatch's U.S. SVOD report for January-September 2025 lists `Prime Video`, `Netflix`, `Disney+`, `HBO Max`, `Hulu`, `Apple TV+`, and `Paramount+` within the main platform market-share group, with `Peacock Premium` trailing that core set.
- Nielsen's January 2026 Media Distributor Gauge shows Netflix still carrying enough TV share to remain a top-tier platform signal, while Disney's bundle/app footprint remains material.
- Official consumer sites confirm the current active product names and standalone service status for Netflix, Prime Video, Disney+, Hulu, Max, Apple TV+, and Paramount+.

## Source links

- JustWatch U.S. SVOD market report: https://www.justwatch.com/us/press/netflix-paramount-warner-bros
- Nielsen January 2026 Media Distributor Gauge: https://www.nielsen.com/news-center/2026/disney-scores-best-performance-in-a-year-in-nielsens-january-2026-media-distributor-gauge/
- Netflix: https://www.netflix.com/?locale=en-US
- Prime Video: https://www.primevideo.com/
- Disney+: https://www.disneyplus.com/
- Hulu: https://www.hulu.com/
- Max: https://help.max.com/us/Answer/Detail/000002543
- Apple TV+: https://tv.apple.com/us
- Paramount+: https://www.paramountplus.com/
