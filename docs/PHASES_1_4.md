# Deep Scan production roadmap: phases 1–4

This document describes the new systems and their limits. The pipeline remains
human-reviewed. No automated score proves a historical claim and no feature
enables unattended public publishing.

## Deep Scan Phase 2: intelligent historical research

The research engine uses deterministic source taxonomy, topic-aware query
expansion, relevance scoring, configurable provider/date controls, and
verbatim candidate-claim extraction. Discovery results and extracted claims
remain unreviewed. Relevance scores are triage metadata, not truth
probabilities. Every extracted sentence retains its source IDs and text
provenance; only a human-reviewed ledger can feed documentary generation.
`src/research_evaluation.py` compares precision@10 using explicit human
labels. The blank `data/research_relevance_evaluation.template.json` has
five topics and must be filled with baseline and Phase 2 top-10 results.
The evaluator refuses missing labels; it never invents relevance judgments.

## Phase 1: historical verification

- \`src/verification.py\` produces \`data/verification_report.json\`.
- Checks ISO date consistency, source-domain diversity, primary-source
  classification metadata, and explicit claim contradiction references.
- DEBATED claims must have sources from at least two domains.
- KNOWN claims with fewer than two source domains or no explicitly classified
  primary/archival/official source receive warnings.
- Metadata completeness scores are not truth probabilities and never approve
  sources or change evidence tiers.
- Documentary QA now includes these checks.

Schema v2 requires each source record to use one canonical source_type value: primary, archival, official_record, academic, institutional, or other. Legacy v1 ledgers are migrated in memory; legacy secondary values map conservatively to other because they do not prove peer review. Classification is metadata only and never approves a source. Claims can optionally use date_start, date_end, date_precision, and conflicts_with.

## Production Phase 2: AI visual reconstruction (separate visual track)

\`src/visuals.py\` connects to a user-hosted ComfyUI server. This avoids locking
the project to a paid image API. Configure:

- \`COMFYUI_BASE_URL\`: ComfyUI server URL reachable from the runner.
- \`COMFYUI_IMAGE_WORKFLOW\`: path to an exported ComfyUI API workflow JSON.
- \`COMFYUI_MEDIA_TYPE\`: \`image\` by default, or \`video\` if the workflow
  produces video output nodes.

The API workflow must contain \`{{PROMPT}}\` in a positive prompt input.
Optional placeholders are \`{{NEGATIVE_PROMPT}}\` and \`{{SEED}}\`. Output nodes
must expose image, video, or GIF outputs in ComfyUI history. The workflow JSON
is user-supplied and should not be committed if it contains private server
details or model paths.

When configured, the daily runner generates per-scene assets, validates
scene-to-claim/source links with `src/visual_qa.py`, and passes the
topic-specific manifest to the renderer. Without ComfyUI configuration, the
existing stock/fallback path is unchanged. Generation needs a reachable
ComfyUI host and suitable installed models; CI does not pretend to have either.

All generated visuals are interpretive AI reconstructions. Preserve the
manifest's claim IDs, source IDs, prompt, seed, and disclosure when reviewing.

## Phase 3: production reliability

- \`src/job_state.py\` writes atomic \`data/job_state.json\` checkpoints.
- Subprocess steps retry up to three times by default with bounded exponential
  backoff; override with \`DEEP_SCAN_STEP_ATTEMPTS\` (1–5).
- Success, retry, and failure details are persisted for diagnosis.
- This is retry/checkpoint visibility, not yet a safe arbitrary-stage resume:
  rerunning a pipeline after failure still revalidates outputs and should be
  done after inspecting the run log and job state.

## Phase 4: channel growth and analytics

- \`src/growth.py\` lints metadata packages and imports YouTube Studio CSV
  exports containing views, impressions, CTR, average percentage viewed, and
  watch time when present.
- It produces \`data/growth_report.json\`; it does not fabricate missing metrics.
- Thumbnail experiments are directional only and require at least 100
  impressions per variant. They do not claim statistical significance or
  causal lift.
- Existing thumbnail generation remains the creative fallback; the experiment
  comparison helper can evaluate manually entered variant metrics.
- SEO metadata now passes a local QA gate before it reaches the review queue.

Example analytics command:

\`\`\`bash
python -m src.growth --analytics-csv data/youtube_studio_export.csv
\`\`\`

## CI and maintenance

The weekly review optionally imports `data/youtube_studio_export.csv` and `data/thumbnail_experiments.json` when supplied. The Deep Scan CI workflow runs Python tests, FFmpeg portrait/landscape smoke
renders, dependency vulnerability auditing, high-severity Bandit checks, and
a credential-file tracking check. Dependabot checks pip and GitHub Actions
dependencies weekly.

A passing CI run also executes `scripts/deep_scan_integration_smoke.py`, which builds a synthetic reviewed ledger, documentary script, SEO package, full-resolution render, and historical/technical QA report without external credentials. A passing CI run proves the tested modules and synthetic renderer work. It
does not prove a live ComfyUI server, real provider credentials, historical
source truth, YouTube upload permissions, or a full external daily production
run. Human review remains required before any upload.
