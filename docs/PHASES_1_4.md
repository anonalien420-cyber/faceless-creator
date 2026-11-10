# Deep Scan production roadmap: phases 1–4

This document describes the new systems and their limits. The pipeline remains
human-reviewed. No automated score proves a historical claim and no feature
enables unattended public publishing.

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

Schema v2 requires each source record to use one canonical source_type value: primary, archival, official_record, academic, institutional, or other. Legacy v1 ledgers are migrated in memory; legacy secondary values map conservatively to other because they do not prove peer review. Classification is metadata only and never approves a source. Claims can optionally use\n
