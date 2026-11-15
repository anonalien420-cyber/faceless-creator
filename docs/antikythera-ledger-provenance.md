# Antikythera evidence ledger — provenance

## What this is

`data/evidence_ledger.json` is the first real (human-reviewed) evidence
ledger on the branch: 12 claims, 6 sources, reviewer Kristian, all
sources `APPROVED`. It was transcribed on 2026-11-15 by Muse from an
existing human review — the published Antikythera long-form — not from
new research, and not by self-approval. The ledger's own `provenance`
field states this in full.

## Source of truth

- Published video: **"The 2,000-Year-Old Object That Shouldn't Exist"**,
  YouTube video `k_wGkEfT5QI`, Public 2026-11-06, 8:08. Description
  carries "Sources you can check": Britannica, Nature 2006, Sci Rep
  2021, National Archaeological Museum Athens.
- Final long-form script:
  `~/workspace/faceless-creator/previews/longform_script.md`
  (mtime 2026-11-05 16:43 UTC).
- First long-form draft:
  `~/workspace/faceless-creator/previews/long_script.txt` and
  `long_script.json` (mtime 2026-11-03 19:53 UTC).
- Gap wording + accuracy annotations:
  `~/workspace/faceless-creator/scripts/antikythera_master_blueprint.md`
  (mtime 2026-11-04 00:31 UTC).

## Review dates per claim

`reviewed_at` is the date the claim entered the reviewed script, from
the file history above — not the transcription date:

| Date | Claims | Why |
|---|---|---|
| 2026-11-03 | antikythera_01, _02, _04, _05, _10, _11 | In the first long-form draft (Nov 3) |
| 2026-11-04 | antikythera_09 | 1,400-year gap wording settled in the blueprint (Nov 4) |
| 2026-11-05 | antikythera_03, _06, _07, _08, _12 | First appear in the final long-form script (Nov 5); the Stais wording in antikythera_03 was approved by Kristian on Nov 5 |

## Sources

| ID | Source | URL |
|---|---|---|
| src_britannica | Encyclopaedia Britannica, "Antikythera mechanism" (2009, updated 2026-09-17) | https://www.britannica.com/topic/Antikythera-mechanism |
| src_nature2006 | Freeth et al., Nature 444, 587–591 (2006), DOI 10.1038/nature05357 | https://doi.org/10.1038/nature05357 |
| src_scirep2021 | Freeth et al., Scientific Reports 11, 5821 (2021), DOI 10.1038/s41598-021-84310-w | https://doi.org/10.1038/s41598-021-84310-w |
| src_nam | National Archaeological Museum, Athens — Collection of Metalwork (Mechanism X15087, Room 38) | https://www.namuseum.gr/en/permanent_exhibition/erga-metallotechnias/ |
| src_thesea | "Antikythera Mechanism Discovery: How It Was Decoded" (thesea.org) | https://thesea.org/antikythera-mechanism-one-amazing-discovery/ |
| src_heritage2021 | Efstathiou et al., Heritage 4(4), 3848–3878 (2021), DOI 10.3390/heritage4040211 | https://doi.org/10.3390/heritage4040211 |

The first four are the video description's own source list; their URLs
come from the repo's `topic_bank.json` / `long_script.json` (Britannica)
and the publishers' DOI records (Nature 2006, Sci Rep 2021), plus the
museum's own collection page (NAM). The last two were added at
transcription time because the description's four sources do not state
two script facts, and each is used only for those facts (recorded in
each source's `notes`):

- `src_thesea` (secondary explainer): the 17 May 1902 gear spotting by
  Valerios Stais, and the case estimate of about 34 × 18 × 9 cm.
- `src_heritage2021` (peer-reviewed): "approximately 3500 letters and
  symbols have been deciphered" via X-ray micro-focusing tomography —
  the backing for the script's "more than 3,000 characters".

Every URL was verified against the real record before transcription
(Britannica and NAM pages fetched 2026-11-15; DOI records confirmed via
the publishers' listings).

## Tier breakdown

12 claims: **10 KNOWN, 1 DEBATED, 1 UNKNOWN.**

- DEBATED: antikythera_11 (2021 UCL cosmos model) — 3 sources, both
  positions, neutral summary, per the `evidence.py` gate.
- UNKNOWN: antikythera_10 (builder/owner) — deliberately sourceless;
  the absence of evidence is the claim.

## Validation

- `python3 -m src.evidence --ledger data/evidence_ledger.json --validate`
  → **PASS** (12 claims, 6 sources).
- `src.verification` report → **PASS**, `needs_review: false`
  (all 12 claims, 0 errors; warnings only: single-domain KNOWN claims
  and the sourceless UNKNOWN claim, as designed).
- `src.documentary` short-form build from the ledger's 7
  `include_in_script` claims → **151 words** (gate 120–180), hook =
  antikythera_01. The other 5 claims stay reviewed evidence for
  longer-form use, not in the Short.

## Deliberately left out

- **The Great Pyramid ledger Echo described does not exist.** Checked
  before writing: not on this branch, not on
  `phase2/source-taxonomy-schema-v2`, not in the AI Command Center
  Drive folder, not locally. No Pyramid claims are recorded here; the
  Antikythera material is used instead, per the task brief.
- **Wreck depth (~45 m).** In the final script but not stated by any
  cited source (one secondary source says ~50 m); omitted rather than
  cited to a conflicting number.
- **Callippic cycle and Exeligmos dials.** In the final script; no
  cited source in the set confirms them. Omitted.
- **Single crank / hand-turned shaft detail.** Minor script detail;
  omitted to keep the ledger at the core facts.
- **"1,500 years" gap variant.** Appears in the blueprint draft; the
  blueprint's own accuracy annotation #3 rejects it in favour of
  1,400. Not used.
- **Precision caveat on the 1,400-year gap.** Both cited sources state
  the gap as "a millennium" (Britannica: "a millennium later"; Nature
  2006: "for at least a millennium afterwards"). The script's "about
  1,400 years" is the gap to the 14th-century cathedral clocks and is
  kept as the reviewed wording; the caveat is recorded in
  antikythera_09's reviewer notes.

## Claim extraction (Phase 2D)

`src/claim_extraction.py` (new, stdlib only) extracts candidate claims
from the abstracts of already-filtered discovery sources: verbatim
sentences only, topic term + verifiable predicate required, tier
suggestion defaults to UNKNOWN (KNOWN only for a measurement/finding
from a primary/academic source), DEBATED never suggested, everything
UNREVIEWED with blank reviewer fields. `extract_from_discovery()` reads
only the kept `sources` list and never `dropped_sources`.
`src/review_packet.py` gained an optional `extracted_claims` parameter
(additive only; existing behaviour unchanged) so the packet can show
extracted candidates as editable templates. Extraction never approves
anything and never writes to the ledger.

## Record packet

`data/review_packet_antikythera.md` / `.json` were generated from the
ledger's own sources via `src/review_packet.py` for the record. Its
generic header warning ("no source or claim in this packet is
approved") is template text; the per-source rows show the ledger's real
state (all 6 APPROVED, with review notes).
