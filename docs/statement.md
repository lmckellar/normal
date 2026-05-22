# Product Statement

As the parser name handling logic expanded and grew in confidence alongside of the additions of caching in conjuction with scan / apply streamlining measures, the application has gone from a "safety first", probe-heavy file renaming tool with unclear boundaries between functions to a hardened, opinionated and deliberate 'purification' workflow that asserts the following.

## A Good Pirate Movie Library Should:

- have the most obvious, clear and consistent naming convention of `Title (Year)`, unless needed to differentiate duplicates and/or alternate version(s)
- define an intended quality stance and library policy in line with this stance, then apply it unanimously while giving the user visibility into its shape and contents
- be clear of Samples, Features, Extras, or other "high load, low pay off" media ephemera

Within the app, these are treated as fixed assumptions.

For `normal`, the quality stance is a firm, anchored preference for material that is of equivlanet quality to modern web streaming services through to 4K remux content with logical gradations scoped in between. 

Lesser quality may be tolerated for less technically demanding or less frequently watched movies, but beneath a certain floor the file is not worth retaining. 

## Physical Storage Economics

`normal` adheres to a principle of **physical storage economics**, whereby the larger in size a media object becomes, the greater the burden of proof becomes on it to justify its existence. 

`normal` considers objectively weak encodes to be worth discarding immediately and regards the safe, orderly and auditable deletion of said objects to be highly relevant and convenient through the process of their replacement

`normal` does not consider maximum bitrate to be the holy grail, nor does it automatically give permission to large packaged metadata files to exist without reason, such as audio tracks with multiple language options.

## Scan Economics

`normal` also adheres to a policy of **scan economics**. It should respect the fact it is reading and writing to a physical drive; as such it should consider performing the breadth of its functions with the absolute minimum of read and write.

This traverses script shape into workflow, boundaries between functions, considerations of maintenance scanning, caching, local storage, and most importantly the assertion of an opinionated downstream object shape and the required steps in order to reach said state, then pursuing that as confidently as the hardening evidence allows the tool to become.

## Opinionated, Yet Merciful

`normal` is opinionated, yet merciful. It understands that mistakes happen and that tastes and technology change. `normal` understands that migrating the centre-mass of quality of a library upward can be painful if the original library shape was anchored on the wrong encode profile. Ask me how I know.

It therefore provides a solution in line with both scan economics and physical storage economics: a "minimum floor of garbage" is defined via profiles, a scan identifies the movies that are garbage, and they are shift-deleted in a single pass that also records them in a register as "deleted, awaiting replacement".

This instantly frees up hard drive space, reduces further scanning overhead, and centralizes the process of replacing weak encodes into a clean and simple list that automatically scans and updates itself, correctly recognizing when a deleted candidate has been replaced and neatly shuffling it off to an audit log of the event.

## Source First, Then Client Quirks

First and foremost, the tool seeks to repair and improve the library files at their source in the most immediately logical way, and will only then consider questions like "how does Plex deal with this specifically compared to Jellyfin?"

## Subtitle and Playback Defaults

`normal` asserts that hands should be devoted to popcorn or the rolling of fine papers at the start of a movie, not fiddling with subtitles.

As such it defines and enforces a logical preference of:

- Forced Subtitles by default if they exist
- English Audio has no subtitle by default
- Foreign Audio primary should have English subtitle by default

## Canon, Quality, and Orientation

`normal` asserts that a library of 5,000 shit films is much weaker than a library of 1,000 excellent, canonically significant films.

As such, it allows the user to directly compare their collection to a curated bucket of TMDB canonical list material for an orientation. It also plans to include a quick-and-dirty regional estimate matrix based off research data that presents a UI element comparing a user library to a known platform.

For example, this may highlight that Australian Netflix users are treated to approximately 7-8 of the IMDb Top 100 as of May 2026 research. A user library with a large mass of high quality encodes in this gravitational centre will naturally destroy the major streaming slop fests in this regard, and `normal` intends to point the way to this.

This is intended to be a lightweight research table pulled from an external server which is periodically updated, but not a hard and fast guarantee of actual provider library shape, as these platforms change often and are technically expensive to parse.

## Confidence, Compression, and Edge Cases

In its journey and evolution, `normal` did not disregard its internal review, proposal, and triaging architecture. It simply grew so confident in it that it began to compress it together, act more and flag less, while becoming more sensitive to genuine edge cases. It become less wasteful elsewhere by folding separate editing stages into single scan and approval passes. 

## An Engineering Trade Off

From its origins as a cheerfully bloated swiss army knife intended for personal use to an increasing cohesive and brutally effective media management system some very real and present trade off's needed to be confronted.

Namely; every lever the user is given to pull is an opportunity to bloat the app in both form and function. Additionally; each lever, if wielded in such a way that it 'differentiated' a single step from a back end perspective, would inevitably flow into library maintability woes as successive re-scans would be required to re-normalize the library accross the different lanes of function (names/folders, deleting weak encodes, remuxxing audio tracks, remuxxing subtitle tracks, deleting sidecar spam, deleting samples/features/etc). I felt this pain and friction myself as the function lanes all came online, became useful and needed to be maintained accross a rolling wave of incoming files into my library. 

The biggest vistims of this development, unfortunately, were the Extras Appreciators and the Fans of Featurettes. These nested files, if allowed to parse into the Normalize lane, will generally cause minor flagging issues and likely push the normalizing logic out of it's comfort zone and lead to missed actions or potentially some oddly garbled naming outputs for the movies that have Extras present. 

The default workflow currently expects these files to be eradicated prior to running the Normalization pass in order to hit a clean one shot against the Media Library. Efforts are being made to include a "blanket policy exemption" that can be applied to the Normalizer but this is not yet in development.

## What Must Be Crystal Clear

`normal` is now aggressive by default and, out of respect, implores the user to perform, at the bare minimum, several simple and logical safety checks against test files on bare metal before so much as allowing a scan to hit their precious library with the tool.

These checks were done as par for the course during development. Do not assume I was willing to trust the actions of this system without verifying an initial set of safe mechanical actions myself. Yet this does not absolve any downstream user of the same responsibility.

1. Goal: ascertain, is `normal` set up correctly, and does it desirably ingest my media, in its current structure, and scan it without issue?  
   Suggested test: make an `Example Movies` directory on your local drive with a representative cross section of your library. Think of this like a Noah's Ark of naming and foldering conventions. You do not need to hit anything yet; the flood is yet to come. You simply want a ground-level sanity check: Python scripts, UI and dependencies are talking, probes are running, and the hood is in fact as "all good" as it is reputed to be.

2. Goal: ascertain drive pathing, scanning, and probing are fine on external hard drive, if using a mechanical drive to store media.  
   Suggested test: copy and paste the `Example Movies` folder across to the hard drive and repeat the same experiment.

How much further you wish to validate system behaviour to gain confidence from there is up to you. It would of course make sense to run your example library through the full range of motion to test all features in turn.

`normal` is set up to easily accommodate this: the test library will simply become a selectable library, as your main library will when you scan it. They each have their own storage and auditing trails and can exist happily side by side, alongside other directories and libraries of course.

Please note: watching the tool absolutely purify your test library will be a thrilling experience the first time you witness it. Be patient. Do not rush to the live library. Stay in your test environment until you are comfortable running live.

## Safety and Visibility

- `normal` will never, ever delete a file on your system without you explicitly performing two approval-gating actions. It is completely 'deterministic' in nature and does not utilise AI inference for naming, logic or any feature in any way (beyond it's development of course).
- `normal` seeks to maximise visibility of what is being changed, why it is being changed, and what it is being changed to, while minimizing friction. The user is intended to review downstream output shape and confirm it is to their liking.
- `normal` will not silently destroy or rename something. All downstream actions are intended to be visible and explicit.

## Audit Logging

`normal` seeks to keep an audit log of actions, although this functionality came late in development and is subsequently half-baked.

It may best be described as currently quite useful, but not a clean and coherent management of state and storage, with a known and notable gap around audit log permanence of "Junk Deleted Items".

The newfound aggression in junk deletion has not yet been paired with a deeper accountability to destructive action logging. This will be addressed soon.
