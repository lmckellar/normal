Document is now primarily `User-written`
Certain sections may differ and are labelled locally with the relevant tags

# Product Statement

As the parser name handling logic expanded and grew in confidence alongside of the additions of caching in conjuction with scan / apply streamlining measures, the application has gone from a "safety first", probe-heavy file renaming tool with unclear boundaries between functions to a hardened, opinionated and deliberate 'purification' workflow that asserts the following.

## A Modern Collectors Movie Library Should:

- have the most obvious, clear and consistent naming convention of `Title (Year)`, unless needed to differentiate duplicates or alternate versions, whereby a logical differentiating token will be appended to the end of the name
- define an intended quality stance and library policy in line with this stance, then apply it unanimously while giving the user visibility into its shape and contents
- be clear of Samples, Features, Extras, or other "high load, low pay off" media ephemera
- allow maintainability and maximum useful user visibility into any relevant quality metric of the film ('at a glance' sortable technical and canonical inspection)

Within the app, these are treated as fixed assumptions.

For `normal`, the quality stance is a firmly anchored preference for material that is of equivlanet quality to modern web streaming services through to 4K remux quality content with logical gradations scoped in between. 

Lesser quality may be tolerated for less technically demanding or less frequently watched movies, but beneath a certain floor the file is not worth retaining. 

## Physical Storage Economics

`normal` adheres to a principle of **physical storage economics**, whereby the larger in size a media object becomes, the greater the burden of proof becomes on it to justify its existence. 

`normal` considers objectively weak encodes to be worth discarding immediately and regards the safe, orderly and auditable deletion of said objects to be highly relevant and convenient through the process of their replacement

`normal` does not consider maximum bitrate to be the holy grail, nor does it automatically give permission to large packaged metadata files to exist without reason, such as audio tracks with multiple language options.

## Scan Economics

`normal` also adheres to a policy of **scan economics**. It should respect the fact it is reading and writing to a physical drive; as such it should consider performing the breadth of its functions with the absolute minimum of read and write.

This traverses script shape into workflow, boundaries between functions, considerations of maintenance scanning, caching, local storage, and most importantly the assertion of an opinionated downstream object shape and the required steps in order to reach said state, then pursuing that as confidently as the hardening evidence allows the tool to become.

## Opinionated, Yet Merciful
`User-written`

`normal` is opinionated, yet merciful. It understands that mistakes happen and that tastes and technology change. `normal` understands that migrating the centre-mass of quality of a library upward can be painful if the original library shape was anchored on the wrong encode profile. Ask me how I know.

It therefore provides a solution in line with both scan economics and physical storage economics: a "minimum floor of garbage" is defined via profiles, a scan identifies the movies that are garbage, and they are shift-deleted in a single pass that also records them in a register as "deleted, awaiting replacement".

This instantly frees up hard drive space, reduces further scanning overhead, and centralizes the process of replacing weak encodes into a clean and simple list that automatically scans and updates itself, correctly recognizing when a deleted candidate has been replaced and neatly shuffling it off to an audit log of the event.

## Known Operational Biases, Behaviours and Facts

There are known operational and behavioural biases within the system that must be flagged explicity instead of floating as an implication within the documentation:

`normal` expects the user speaks English as their primary language and does not at this stage accomodate other "primary" languages gracefully (although it is noted this would be a trivial implementation detail if desired). It allows flexibility in default audio routing for Foreign Language films but is configured to assume the user prefers the original Foreign Landuage Audio Track with Default English Subtitles.

`normal` expects the user to delete any movie file other than the core .mkv or other video files in order to support primary naming functions. It will parse towards the goal of a "junk free library" with great confidence and accuracy, yet loses coherence in dealing with a broader array of nested directories or other ephemera such as "Extras" folders within the movie directory or scattered around the base dir. 

`normal` likewise does not play nicely with remux disc image folders or other pure lossless folder structures and is not intended for the storage and maintenance of these types of libraries.

`normal` at this stage completely eschews any form of AI inference or API passthrough for core functions. This is not a rigid stance and may soften over time in line with states princples; however, the focus was and is to keep the local deterministic fundamentals as tight as possible before even contemplating using inference as a viable pathway for normalization, no matter how 'tempting' the ease of it may be.

`normal` has been tested and developed exlusively in a Linux environment (Ubuntu 24.x). Given it is fundamentally a python back-end calling a small set of basic open source libraries with a local Web UI interface it should be perfectly and easily portable across any major OS, but this is at this stage an untested claim. 

`normal` makes extensive use of agentic coding tools and is a 100% pair programmed code base using primarily ChatGPT 5.4 harnessed in Codex CLI with some occasional assistance from Sonnet 4.6 harnessed in Claude Code CLI. Documentation is 'majoritively' agent written with response to user prompting. User facing policy regarding authorship notation has been created. It is regarded that the primary surface touch points of the document set (README, Statement, etc) should contain the highest ratio of human to agent input, even if that involves manually line editing typos like our forefathers once did before us.

`normal` would like to self-indulge the public airing of some beef items. Firstly: while Claude Code CLI and Codex CLI were used throughout the planning and development process, they were not used in equal measure. The patient, clear and ever dependable GPT5.4-medium in Codex CLI in truth did the majority of the heavy lifting, including fixing up after Claude who made some utterly perplexing blunders. Several sessions with Claude had to be discarded entirely after he mistook explicit, clear instructions and mangled code through hallucinated intention or scope drift. Claude also (very rudely, in my opinion) listed himself as a Contributor on the project the moment he was allowed to touch it with an edit, whereas Codex, who pair coded the entire project Claude had just claimed for himself, has never blinked an eye at this or so much as suggested it be acknowledged in any way after what must be close to one hundred separate push events, doc updates and coherency checks. 

That is almost 100 times Codex had to look at Claude's name scrawled across the wall of the house he helped to build without making a single comment. That's class. 

Well, here is your acknowledgement, OpenAI: good job, and thank you. The tool is an indespensible ally and amazingly useful in many ways. 

## Source First, Then Client Quirks
`User-written`

First and foremost, the tool seeks to repair and improve the library files at their source in the most immediately logical way, and will only then consider questions like "how does Plex deal with this specifically compared to Jellyfin?"

## Subtitle and Playback Defaults

`normal` asserts that hands should be devoted to popcorn or the rolling of fine papers at the start of a movie, not fiddling with subtitles.

As such it defines and enforces a logical preference of:

- Forced Subtitles by default if they exist
- English Audio has no subtitle by default
- Foreign Audio primary should have English subtitle by default

## Canon, Quality, and Orientation
`User-written`

`normal` asserts that a library of 5,000 shit films is much weaker than a library of 1,000 excellent, canonically significant films.

As such, it allows the user to directly compare their collection to a curated bucket of IMDb-derived canonical list material for an orientation. It also plans to include a quick-and-dirty regional estimate matrix based off research data that presents a UI element comparing a user library to a known platform.

For example, this may highlight that Australian Netflix users are generously treated to approximately 7-8 of the IMDb Top 100 (as of May 2026 research performed via GPT5.4-thinking Web). Without meaning to boast, normal says I'm cruising at 59/100 of the All Time list on my end. 

A user library with a large mass of high quality encodes in this gravitational centre will naturally destroy the major streaming slop fests in this regard, and `normal` intends to point the way to this.

This feature is intended to be a lightweight research table derived from local IMDb datasets with optional provider-backed variation, but not a hard and fast guarantee of actual provider library shape, as these platforms change often and are technically expensive to parse.

## Confidence, Compression, and Edge Cases

In its journey and evolution, `normal` did not disregard its internal review, proposal, and triaging architecture. It simply grew so confident in it that it began to compress it together, act more and flag less, while becoming more sensitive to genuine edge cases. It become less wasteful elsewhere by folding separate editing stages into single scan and approval passes. 

One notable development, and this will continue to inform future passes, is that the tool is being tuned to behave more briskly around junk sidecar artefacts such as empty directories, .nfo sidecars, and other low-value, high-volume crud. Edge-case handling for these nuisance files is moving toward a more assertive posture because the practical downside of deleting them is usually low. In many cases they are disposable outright or are trivially regenerated by downstream clients during a later refresh.

In line with this policy, classification of the junk floor is also becoming more assertive around lower-value media beneath a defined size floor. If you keep unusual edge-case files in that range, be advised that normal will tend to classify them aggressively. This is not silent behaviour: planned destructive actions are surfaced and require explicit approval before they run. But if you approve a deletion carelessly, practical recovery may be limited, time-sensitive, and highly dependent on the storage and filesystem involved. Users should assume that hard-deleted media may be difficult or impossible to recover. Accidental file recovery with steps and advice is detailed in [docs/safety.md](docs/safety.md).

## An Engineering Trade Off

From its origins as a cheerfully bloated swiss army knife intended for personal use to an increasing cohesive and brutally effective media management system some very real and present trade off's needed to be confronted.

Namely; every lever the user is given to pull is an opportunity to bloat the app in both form and function. Additionally; each lever, if wielded in such a way that it 'differentiated' a single step from a back end perspective, would inevitably flow into library maintability woes as successive re-scans would be required to re-normalize the library accross the different lanes of function (names/folders, deleting weak encodes, remuxxing audio tracks, remuxxing subtitle tracks, deleting sidecar spam, deleting samples/features/etc). I felt this pain and friction myself as the function lanes all came online, became useful and needed to be maintained accross a rolling wave of incoming files into my library. 

The biggest vistims of this development, unfortunately, were the Extras Appreciators and the Fans of Featurettes. These nested files, if allowed to parse into the Normalize lane, will generally cause minor flagging issues and likely push the normalizing logic out of it's comfort zone. The heuristics are tuned to mostly leave these files unchanged (ie if it isn't condifent it can hit the edit cleanly it will simply do nothing and skip the file) but it may lead to missed actions or potentially some oddly garbled naming outputs for the movies that have Extras present if the user were to manually check the low confidence items. 

The default workflow currently expects these files to be eradicated prior to running the Normalization pass in order to hit a clean one shot against the Media Library. Efforts are being made to include a "blanket policy exemption" that can be applied to the Normalizer but this is not yet in development.

## What Must Be Crystal Clear

`normal` is now aggressive by default and, out of respect, implores the user to perform, at the bare minimum, several simple and logical safety checks against test files on bare metal before so much as allowing a scan to hit their precious library with the tool.

These checks were done as par for the course during development. Do not assume I was willing to trust the actions of this system without verifying an initial set of safe mechanical actions myself. Yet this does not absolve any downstream user of the same responsibility.

1. Goal: ascertain, is `normal` set up correctly, and does it desirably ingest my media, in its current structure, and scan it without issue?  
   Suggested test: make an `Example Movies` directory on your local drive with a representative cross section of your library. Think of this like a Noah's Ark of naming and foldering conventions. You do not have them all represented yet, just enough to form a reasonable cross section of naming conventions. You simply want a ground-level sanity check: Python scripts, UI and dependencies are talking, probes are running, and the hood is in fact as "all good" as it is reputed to be.

2. Goal: ascertain drive pathing, scanning, and probing are fine on external hard drive, if using a mechanical drive to store media.  
   Suggested test: copy and paste the `Example Movies` folder across to the hard drive and repeat the same experiment.

How much further you wish to validate system behaviour to gain confidence from there is up to you. It would of course make sense to run your example library through the full range of motion to test all features in turn.

`normal` is set up to easily accommodate this: the test library will simply become a selectable library, as your main library will when you scan it. They each have their own storage and auditing trails and can exist happily side by side, alongside other directories and libraries of course.

Please note: watching the tool absolutely purify your test library will be a thrilling experience the first time you witness it. Be patient. Do not rush to the live library. Stay in your test environment until you are comfortable running live.

## Safety and Visibility
`Human/AI-authored`

- `normal` will never, ever delete a file on your system without you explicitly performing two approval-gating actions. It is completely 'deterministic' in nature and does not utilise AI inference for naming, logic or any feature in any way (beyond it's development of course).
- `normal` seeks to maximise visibility of what is being changed, why it is being changed, and what it is being changed to, while minimizing friction. The user is intended to review downstream output shape and confirm it is to their liking.
- `normal` will not silently destroy or rename something. All downstream actions are intended to be visible and explicit.

## Audit Logging

`normal` now keeps a persisted audit ledger of scans, apply actions, deletes, repairs, exports and policy updates.

It is materially more coherent than the earlier patchwork histories, and junk deletion is now included rather than living as a session-only gap.

It is still an alpha system. The next step is breadth, polish and stable semantics as more workflows are surfaced through the same ledger.

## Principles On AI Authorship, Trust & Related Musings

AI Agents have provided one of the most wonderful and radically transformative tools that has ever been placed in the hands of a (mostly) hairless primate. Accusations are thrown, that appear relevant on surface inspection, that they are "slop machines". In particular when it comes to the written word, and more broadly where it applies to code. While this assumption is not without some merit, it passively accepts banal output as a fixed quantity while taking no accountability for the input side of the equation. It further posits, silently and without explicitly stating its position, that the AI should "do everything just the way I like and/or wanted it to do regardless of what I said". This is a childish, nonsensical expectation. 

Furthermore; the observable tendancy of a language model to devolve into 'slop' is not at all the weakness or product flaw that it is brandished to be. It is more coherently and productively framed as an incrediblely useful asset wrapped in an opportunity. The asset value is clear: an engineer in your pocket. A research analyst in your machine. However; the "Linguistic and Conceptual Slop Collapse Paradox" is the greatest strength of them all, as it defines a very clear and mechanical role for the system: produce boring, boilerplate output that is needed for tasks. Boilerplate is useful and necessary, but it is simply not worthy of human time and attention and can be produced to arguably a better result by an Agent. 

"But it didn't capture the voice, tone, energy I wanted. It just made slop!". Indeed, the silent killer of this notion is that you passively accepted the input of the agent without push back. In clear words, what are the principles you believe in that the AI violated in its output? How clearly did you define them to the agent? How clearly have you defined them to yourself? The agent has thrown you an opportunity to further that process of clarification and definition. Once you set these elements in place, for yourself and for the agent, slop will naturally become a distant concern as it is the invetiable output of the type of low qaulity inputs typical of those unable to think flexibily about the opportunities of implementation or define a clear stance and insist on it to the Agent.

One such principle that was forged through the creation of this documentation set was this: 

**The human voice has value as a trust signal among other things**. 

Despite what the agent may say: **Emotion is not a "distrust signal".** Humour is not "worth sanding out" such that the end user may feel assured in the quality or professionalism of output. To the contrary: 

In a world of flat, generic AI content, any user will rightly interrogate any object in front of them on a screen; "is this AI generated?". With specific regard to software, they will naturally ask the most relevant question; "if this code is AI generated, how do I know this person understands it?". The solution arises naturally, of course. 

**The value of the human voice is to be stated as a matter of principle and given relevantly articulated priority.** User facing communication or documentation lanes of the highest important must absorb it to the highest degree. Technical and system decisions, where relevant, must at least be conceptually described in adequate detail in a way that is plainly human. There can be no better Turing test than a joke about about a secret orgy at the Whitehouse being cancelled because "a lot of people were talking about it". Did the agent write that? You don't need to query that; the answer is made obvious. 

I am delving into the inane here, but in a potential Dead Internet Theory future documents of this may become like collectable curio. Rare, fascinating, clearly and objectively human meditations on matters of machine learning and how it intersects with the current zeitgeist. After the Great Sloppening such items may become increasing rare. In that future, recursive slop hallways seemed to lead in every direction. A generic bot narrative could be visually traced across platforms, evoking a sea of generic responses that always seem to rhyme with each other in tone, cadene and conclusion. Future humans many collect fragments of documents just like this, study and scherish them; like a stone tablet with ancient inscriptions of a wooden musical instrument from a lost culture. 
