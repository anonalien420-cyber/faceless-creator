# Content policy

These rules are enforced in code (QA gate, `drop_unverified`, thumbnail
`validate_claim`) and are not optional.

## Originality
Scripts are generated from an original angle (hook, beats/sections, CTA)
using only the candidate's topic as a prompt. Never copy a source video's
title, script, or wording; never reuse copyrighted characters or music;
never present a paraphrase of someone else's script as your own. A
candidate with no usable topic is skipped, not copied. Thumbnails use only
this project's own visuals (or an original gradient) — never another
creator's thumbnail or copyrighted art.

## Historical accuracy (history-mystery style)
Every section carries a claim tier:
- **KNOWN** — verified, sourced fact. Must have a real source in `sources`.
- **DEBATED** — genuine disagreement; both sides named, neither settled.
- **UNKNOWN** — genuinely unexplained; stated plainly, never guessed at.

No invented dates, names, quotes, artifacts, or findings. Any concrete
claim without a real source is **dropped** (`drop_unverified`), not
softened into a guess, and listed in `dropped_unverified`. The QA accuracy
gate blocks upload until sources are filled and sections are tiered.

Evidence first, competing theories labelled as theories, and a clear
what-is-still-unexplained section. Every video ends with an open viewer
question ("What do you think happened?") plus a next-episode tease.

## Shock, honestly
A history video opens with a verified **shock hook** — a genuinely
surprising but TRUE fact (scale, contrast, or twist), labelled KNOWN, with
its source in `shock_hook`. Shock comes from real facts, never from
exaggeration, invented numbers, or misleading framing. A shock claim
without a source is dropped and blocks upload. `research.py` can supply a
sourced shock candidate from Wikipedia (verbatim, with its URL); the
creator still verifies it in the review queue before publishing.

Viewer speculation is engagement, never evidence: a commenter's theory
must never be presented in a later video as fact.

## Thumbnail truth
`validate_claim` refuses any thumbnail text whose claim is not in the
script: a `$X` amount must appear in the script; a `#N` must refer to a
real numbered item; other content words must appear in the script/topic
(generic curiosity words are exempt). A refused claim falls back to a
truthful, topic-based curiosity line — visibly, not silently. Misleading
thumbnails risk YouTube strikes and viewer distrust.

## Music
Only royalty-free tracks (or a track you hold a licence for, logged with
its licence note). Never substitute the actual trending copyrighted song.
If no library track matches the trending profile, the pipeline fails
loudly naming the wanted profile rather than using an unrelated track.

## What is never auto-done
Deleting videos, changing a video's privacy after publishing, changing
channel settings, or spending money. Anything beyond the weekly review's
safe bounds is a recommendation for the human, not an auto-change.
