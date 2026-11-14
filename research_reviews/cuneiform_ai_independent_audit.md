# Cuneiform AI — independent evidence audit

**Audit date:** 2026-11-13  
**Branch:** `phase2/intelligent-historical-research`  
**Scope:** Independent source/claim assessment of `research_packages/cuneiform_ai_review_packet.md`.  
**Important:** This is an audit recommendation, not a human approval. No canonical evidence-ledger status or approval field is changed.

## Executive finding

The four sources are authentic and relevant. The packet's central distinction is essential: OCR, transliteration/segmentation, and machine translation are separate tasks with different inputs and error rates. The evidence supports saying that AI systems can assist specialists with parts of the cuneiform research workflow. It does not support claiming that AI can autonomously and reliably translate every tablet, or that Akkadian texts contain modern slang.

A particularly useful primary-source detail is that the 2023 Akkadian translation paper reports substantial error and hallucination rates in its own human-evaluated samples. This should be included in the story rather than buried as a footnote.

## Source-by-source assessment

### cun_src_001 — Neural machine translation for Akkadian

**Source:** Gai Gutherz, Shai Gordin, Luis Sáenz, Omer Levy, and Jonathan Berant, “Translating Akkadian to English with neural machine translation,” *PNAS Nexus* 2(5), pgad096 (2023), DOI [10.1093/pnasnexus/pgad096](https://doi.org/10.1093/pnasnexus/pgad096).

**Recommendation:** APPROVE FOR HUMAN REVIEW — high confidence for the reported model tasks and metrics; strong caution required for quality claims.

**What is supported:** The paper presents two Akkadian-to-English tasks: C2E (Unicode cuneiform glyphs to English) and T2E (scholarly transliteration to English). It reports BLEU4 scores of 36.52 for C2E and 37.47 for T2E, with best results on short- and medium-length sentences (about 118 characters or fewer).

**Critical limitations:** BLEU4 is an automatic comparison metric, not a percentage of correct translations. In the paper's 50-sentence human-evaluation samples, the C2E task had 14 proper translations, 18 hallucinations, and 22 improper translations; T2E had 16 proper translations, 12 hallucinations, and 22 improper translations. The authors show examples where the model omitted negation or confused a word with another possible reading. They explicitly say even apparently proper outputs need expert evaluation. The model is a research aid, not a replacement for Assyriologists.

**Suggested ledger wording:** “A 2023 study trained neural machine-translation models for Akkadian-to-English translation from both Unicode cuneiform glyphs and scholarly transliterations, reporting BLEU4 scores of 36.52 and 37.47 respectively.”

**Human reviewer should inspect:** Abstract, Materials and Methods, evaluation/results, qualitative human-evaluation samples, discussion, and supplementary data. Cite the test-sample sizes and error categories when discussing reliability.

### cun_src_002 — NLP transliteration and segmentation

**Source:** Shai Gordin et al., “Reading Akkadian cuneiform using natural language processing,” *PLOS ONE* 15(10): e0240511 (2020), DOI [10.1371/journal.pone.0240511](https://doi.org/10.1371/journal.pone.0240511).

**Recommendation:** APPROVE FOR HUMAN REVIEW — high confidence for the task and reported test metrics.

**What is supported:** The paper develops machine-learning methods to transliterate and segment standard Unicode cuneiform glyphs into words. Its best BiLSTM model reports 96.7% accuracy when transliteration and segmentation are both counted, 97.8% for transliteration alone, and 97.9% F1 for segmentation alone.

**Critical limitations:** These are not English-translation accuracy figures. The paper describes this as the first two stages toward translation and a human-machine interface for producing digitized editions. Its error analysis identifies ambiguity between logographic and phonetic readings and mistakes in word segmentation.

**Suggested ledger wording:** “A 2020 study reported up to 96.7% combined accuracy for automatically transliterating and segmenting standard Unicode cuneiform glyphs into words.”

**Human reviewer should inspect:** Abstract, methods, Table 2, results/discussion, error analysis, and conclusion. Prefer the exact 96.7% combined metric when making a combined claim; if quoting 97.8%, label it transliteration-only.

### cun_src_003 — CuReD OCR for cuneiform text editions

**Source:** Shai Gordin, Morris Alper, Avital Romach, Luis Sáenz Santos, Naama Yochai, and Roey Lalazar, “CuReD: Deep Learning Optical Character Recognition for Cuneiform Text Editions and Legacy Materials,” *Proceedings of the 1st Workshop on Machine Learning for Ancient Languages* (ML4AL 2024), pp. 130–140, DOI [10.18653/v1/2024.ml4al-1.14](https://doi.org/10.18653/v1/2024.ml4al-1.14).

**Recommendation:** APPROVE FOR HUMAN REVIEW — high confidence for the stated OCR task and character-error figures.

**What is supported:** CuReD is a deep-learning, human-in-the-loop OCR pipeline for digitizing scans of printed cuneiform text editions that are already presented in scholarly transliteration. It reports character error rates of 9% on clean data and 11% on representative scans.

**Critical limitations:** This is OCR of scanned printed transliterations and legacy text materials. It is not direct recognition of wedge marks from photographs or 3D scans of raw clay tablets, and character error rate is not translation accuracy. The human-in-the-loop description matters: output is intended for checking and correction.

**Suggested ledger wording:** “A 2024 project introduced a human-in-the-loop OCR pipeline for scanned scholarly transliterations of cuneiform texts, reporting character error rates of 9% on clean data and 11% on representative scans.”

**Human reviewer should inspect:** Abstract, dataset description, system/pipeline, evaluation protocol, and error analysis (PDF pp. 130–140).

### cun_src_004 — Survey of machine learning for ancient languages

**Source:** Thea Sommerschield et al., “Machine Learning for Ancient Languages: A Survey,” *Computational Linguistics* 49(3) (2023), pp. 703–747, DOI [10.1162/coli_a_00481](https://doi.org/10.1162/coli_a_00481).

**Recommendation:** APPROVE FOR HUMAN REVIEW — high confidence as broad field context.

**What is supported:** The survey organizes machine-learning research on ancient texts across distinct tasks, including digitization, restoration, attribution, linguistic analysis, textual criticism, translation, and decipherment. It emphasizes collaboration between humanities specialists and machine-learning researchers.

**Critical limitations:** This is a broad survey, not direct validation of the Akkadian models above. Use it to explain the field and the need for interdisciplinary work, not as proof of a particular model's accuracy.

**Suggested ledger wording:** “A 2023 survey maps machine-learning applications to ancient texts across digitization, restoration, linguistic analysis, translation, and decipherment, and emphasizes collaboration with domain specialists.”

**Human reviewer should inspect:** Taxonomy and sections on digitization/recognition, linguistic analysis, machine translation, and decipherment.

## Claim worksheet decisions

| Claim | Audit recommendation | Required wording / caveat |
|---|---|---|
| cun_claim_001 | APPROVE FOR HUMAN REVIEW | Clearly distinguish C2E from T2E and identify the 2023 paper's model as research assistance. |
| cun_claim_002 | APPROVE FOR HUMAN REVIEW, ADD LIMITATION | State the BLEU4 scores exactly; explain BLEU is not translation accuracy and include human-evaluation error findings. |
| cun_claim_003 | APPROVE FOR HUMAN REVIEW, REWORD | Prefer “96.7% combined transliteration-and-segmentation accuracy”; 97.8% applies to transliteration only. Neither is English translation accuracy. |
| cun_claim_004 | APPROVE FOR HUMAN REVIEW, REWORD | State OCR operates on scans of printed scholarly transliterations, not raw clay tablet images; character error rate is not translation accuracy. |

## Editorial guardrails

- Keep OCR, transliteration, segmentation, and translation as four distinct workflow stages.
- Never describe 97% transliteration/segmentation as 97% translation accuracy.
- Never describe BLEU4 as a percentage of correct translations.
- Include the 2023 paper's human-evaluation errors and hallucinations when making claims about model capability.
- Explain that CuReD digitizes scans of scholarly transliterations, not raw tablet photographs.
- Acknowledge expert review as necessary; human-in-the-loop is not a decorative phrase.
- Modern slang must be explicitly labeled as a humorous paraphrase or creative adaptation, never as a literal Akkadian translation.
- Do not invent a slang translation or present an AI-generated line as a verified ancient quotation.

## Recommended factual episode framing

**Title:** “Can AI Read 4,000-Year-Old Writing? What Akkadian Research Actually Shows”

**Hook:** “AI can now help turn ancient cuneiform into readable data and even draft English translations. But the researchers' own tests show why a human expert still has to check the result.”

**Narrative boundary:** Present modern slang as a playful modern paraphrase of a verified scholarly translation, with the source translation shown or cited. Do not pass the paraphrase off as what an ancient scribe literally wrote.

## Source links

1. [Gutherz et al. 2023, PNAS Nexus full text](https://academic.oup.com/pnasnexus/article/2/5/pgad096/7147349)
2. [Gordin et al. 2020, PLOS ONE full text](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0240511)
3. [Gordin et al. 2024, ACL Anthology paper](https://aclanthology.org/2024.ml4al-1.14/)
4. [Sommerschield et al. 2023, ACL Anthology survey](https://aclanthology.org/2023.cl-3.5/)

**Final status:** Independent audit complete. All four source recommendations are for human review only. The canonical ledger remains unchanged and all packet claims remain unapproved pending the required human review.
