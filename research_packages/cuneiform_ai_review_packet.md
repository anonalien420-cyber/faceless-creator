# Cuneiform AI evidence review package

**Episode candidate:** AI Tech Mystery: When Cuneiform Met Modern Slang  
**Status:** REVIEW REQUIRED. No source or claim is approved.

## Editorial guardrail

The research supports AI-assisted OCR, transliteration/segmentation, and Akkadian-to-English machine-translation experiments. It does **not** show that ancient cuneiform contains modern slang or that AI output can be treated as an authoritative translation without expert review.

If the video uses modern slang, label it as a playful paraphrase or creative adaptation. Never call it a literal translation.

## Source review queue

### cun_src_001 — Neural machine translation for Akkadian

- **Paper:** Gai Gutherz, Shai Gordin, Luis Sáenz, Omer Levy, and Jonathan Berant, “Translating Akkadian to English with neural machine translation,” *PNAS Nexus* 2(5), pgad096 (2023).
- **Original article:** https://academic.oup.com/pnasnexus/article/2/5/pgad096/7147349
- **DOI:** https://doi.org/10.1093/pnasnexus/pgad096
- **Review anchor:** Abstract, methods, results, discussion, and supplementary data.
- **Candidate relevance:** Presents neural machine-translation tasks from cuneiform Unicode glyphs to English and from transliteration to English. Reports BLEU4 scores of 36.52 and 37.47.
- **Critical limitation:** BLEU is an automatic similarity metric, not proof of correct translation. The paper reports best results on shorter and medium-length sentences (about 118 characters or less) and discusses hallucinations and errors. The authors describe the system as a human-machine collaboration tool.

### cun_src_002 — NLP transliteration and segmentation

- **Paper:** Shai Gordin et al., “Reading Akkadian cuneiform using natural language processing,” *PLOS ONE* 15(10): e0240511 (2020).
- **Original article:** https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0240511
- **DOI:** https://doi.org/10.1371/journal.pone.0240511
- **Review anchor:** Abstract, methods, evaluation, and error analysis.
- **Candidate relevance:** Reports up to 97% accuracy for automatic transliteration and segmentation of standard Unicode cuneiform glyphs into words.
- **Critical limitation:** The 97% figure is for transliteration/segmentation, not end-to-end English translation or slang generation.

### cun_src_003 — OCR for cuneiform text editions

- **Paper:** Shai Gordin et al., “CuReD: Deep Learning Optical Character Recognition for Cuneiform Text Editions and Legacy Materials,” *Proceedings of the 1st Workshop on Machine Learning for Ancient Languages* (ML4AL 2024), pp. 130–140.
- **Original article:** https://aclanthology.org/2024.ml4al-1.14/
- **DOI:** https://doi.org/10.18653/v1/2024.ml4al-1.14
- **Review anchor:** Abstract, dataset description, evaluation, and PDF pp. 130–140.
- **Candidate relevance:** Describes a human-in-the-loop OCR pipeline for scanned transliterations of cuneiform text editions, reporting 9% character error on clean data and 11% on representative scans.
- **Critical limitation:** This is OCR for scanned editions/transliterations, not direct reading of raw clay tablets. Character error rate is not translation accuracy.

### cun_src_004 — Survey of machine learning for ancient languages

- **Paper:** Thea Sommerschield et al., “Machine Learning for Ancient Languages: A Survey,” *Computational Linguistics* 49(3).
- **Original record:** https://submissions.cljournal.org/index.php/cljournal/article/view/2307
- **Review anchor:** Survey taxonomy and sections on digitization, restoration, translation, and decipherment.
- **Candidate relevance:** Surveys machine-learning tasks for ancient texts and emphasizes collaboration between humanities specialists and machine-learning researchers.
- **Critical limitation:** This is field context, not direct validation of a specific translation model.

## Candidate claim worksheet

1. **cun_claim_001 — KNOWN candidate.** A 2023 study presented neural machine-translation models for Akkadian-to-English translation from cuneiform Unicode glyphs and transliteration. Source: cun_src_001.
2. **cun_claim_002 — KNOWN candidate.** The 2023 study reported BLEU4 scores of 36.52 and 37.47 for its two tasks and stronger performance on short and medium-length sentences. Source: cun_src_001.
3. **cun_claim_003 — KNOWN candidate.** A 2020 study reported up to 97% accuracy for automatic transliteration and segmentation of standard Unicode cuneiform glyphs into words. Source: cun_src_002.
4. **cun_claim_004 — KNOWN candidate.** A 2024 project developed a human-in-the-loop OCR pipeline for scanned cuneiform editions and reported character error rates of 9% on clean data and 11% on representative scans. Source: cun_src_003.

## Unsupported claims

- AI can reliably translate every cuneiform tablet without expert review.
- Ancient Akkadian texts contain modern slang.
- A 97% transliteration/segmentation result means 97% translation accuracy.
- OCR of scanned transliterations is equivalent to reading an unprocessed photograph of a clay tablet.

## Human review instructions

Read the methods, evaluation data, and limitations in each paper. Keep OCR, transliteration, segmentation, and translation as separate technical tasks. Do not treat BLEU scores as human translation accuracy. If modern slang is used in the narration, label it as a humorous paraphrase, never as a literal translation. No claim enters the evidence ledger until a human reviewer approves the source and records an exact reference.
