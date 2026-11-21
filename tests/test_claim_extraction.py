import unittest

from src.claim_extraction import (
    extract_claims,
    extract_from_discovery,
    source_text,
    split_sentences,
)
from src.review_packet import build_packet, render_markdown


# Fixture abstracts are synthetic sentences written for these tests
# (modelled on the Antikythera discovery record). They are test data,
# not historical claims, and no test asserts any of them is true.
ABSTRACT = (
    "The Antikythera Mechanism is a unique Greek geared device, constructed "
    "around the end of the second century BC. It was discovered in 1901 in "
    "a Roman shipwreck, and it contains 30 bronze gear wheels. The mechanism "
    "predicted lunar and solar eclipses on the basis of Babylonian cycles. "
    "Researchers have long wondered about its origins."
)

ACADEMIC = {
    "source_id": "src_0001",
    "title": "Decoding the Antikythera Mechanism",
    "provider": "Crossref",
    "source_type": "academic",
    "abstract": ABSTRACT,
}

INSTITUTIONAL = {
    "source_id": "src_0002",
    "title": "Antikythera mechanism overview",
    "provider": "Museum",
    "source_type": "institutional",
    "abstract": (
        "The Antikythera Mechanism was recovered in 1901 from a trading "
        "ship that sank near the island of Antikythera. It contains 30 "
        "bronze gear wheels."
    ),
}

TOPIC = "Antikythera Mechanism"


class SentenceSplittingTests(unittest.TestCase):
    def test_decimal_does_not_split_sentence(self):
        parts = split_sentences(
            "The Saros cycle lasts 18.2 years. The Antikythera Mechanism "
            "predicted eclipses.")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].endswith("18.2 years."))

    def test_empty_and_blank_input_yields_no_sentences(self):
        self.assertEqual(split_sentences(""), [])
        self.assertEqual(split_sentences("   "), [])

    def test_abbreviation_does_not_split_sentence(self):
        parts = split_sentences(
            "The Antikythera Mechanism, e.g. the gear train, was studied.")
        self.assertEqual(len(parts), 1)


class SourceTextTests(unittest.TestCase):
    def test_plain_abstract_is_used_verbatim(self):
        self.assertEqual(source_text(ACADEMIC), ABSTRACT)

    def test_inverted_index_is_rebuilt(self):
        source = {"abstract_inverted_index": {
            "The": [0], "Antikythera": [1], "Mechanism": [2],
            "contains": [3], "30": [4], "gears": [5]}}
        self.assertEqual(source_text(source),
                         "The Antikythera Mechanism contains 30 gears")

    def test_no_abstract_yields_empty_string(self):
        self.assertEqual(source_text({"source_id": "s1", "title": "T"}), "")
        self.assertEqual(source_text({}), "")
        self.assertEqual(source_text(None), "")


class ExtractClaimsTests(unittest.TestCase):
    def test_extracted_text_is_verbatim_source_sentence(self):
        claims = extract_claims([ACADEMIC], TOPIC)
        self.assertTrue(claims)
        for claim in claims:
            self.assertIn(claim["text"], ABSTRACT)

    def test_measurement_sentence_from_academic_source_suggests_known(self):
        claims = extract_claims([ACADEMIC], TOPIC)
        by_text = {c["text"]: c for c in claims}
        eclipse = ("The mechanism predicted lunar and solar eclipses on the "
                   "basis of Babylonian cycles.")
        self.assertIn(eclipse, by_text)
        self.assertEqual(by_text[eclipse]["suggested_status"], "KNOWN")
        self.assertEqual(by_text[eclipse]["source_ids"], ["src_0001"])
        self.assertEqual(by_text[eclipse]["extraction_method"],
                         "abstract_sentence")
        self.assertTrue(by_text[eclipse]["extracted"])

    def test_generic_sentence_without_predicate_is_not_extracted(self):
        claims = extract_claims([ACADEMIC], TOPIC)
        texts = [c["text"] for c in claims]
        self.assertNotIn("Researchers have long wondered about its origins.",
                         texts)

    def test_sentence_without_topic_terms_is_not_extracted(self):
        source = dict(ACADEMIC, abstract=(
            "The Antikythera Mechanism contains 30 bronze gear wheels. "
            "It predicted lunar and solar eclipses."))
        claims = extract_claims([source], TOPIC)
        self.assertEqual(
            [c["text"] for c in claims],
            ["The Antikythera Mechanism contains 30 bronze gear wheels."])

    def test_nothing_is_auto_approved(self):
        claims = extract_claims([ACADEMIC], TOPIC)
        for claim in claims:
            self.assertEqual(claim["review_status"], "UNREVIEWED")
            self.assertEqual(claim["reviewed_by"], "")
            self.assertEqual(claim["reviewed_at"], "")
            self.assertFalse(claim["include_in_script"])
            self.assertEqual(claim["status"], "UNKNOWN")
            self.assertNotEqual(claim["suggested_status"], "DEBATED")

    def test_non_academic_source_defaults_to_unknown_suggestion(self):
        claims = extract_claims([INSTITUTIONAL], TOPIC)
        self.assertTrue(claims)
        for claim in claims:
            self.assertEqual(claim["suggested_status"], "UNKNOWN")

    def test_empty_abstract_yields_no_claims_without_crashing(self):
        self.assertEqual(extract_claims(
            [{"source_id": "s1", "title": "Empty", "abstract": ""}], TOPIC),
            [])
        self.assertEqual(extract_claims(
            [{"source_id": "s1", "title": "No abstract"}], TOPIC), [])

    def test_degenerate_inputs_do_not_crash(self):
        self.assertEqual(extract_claims([], TOPIC), [])
        self.assertEqual(extract_claims(None, TOPIC), [])
        self.assertEqual(extract_claims([ACADEMIC], ""), [])
        self.assertEqual(extract_claims([{"title": "No id"}], TOPIC), [])
        self.assertEqual(extract_claims(["not a dict"], TOPIC), [])
        self.assertEqual(extract_claims([None], TOPIC), [])

    def test_multi_source_agreement_links_both_sources(self):
        shared = ("The Antikythera Mechanism contains 30 bronze gear "
                  "wheels.")
        first = dict(ACADEMIC, abstract=shared)
        second = dict(INSTITUTIONAL, abstract=shared)
        claims = extract_claims([first, second], TOPIC)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["source_ids"],
                         ["src_0001", "src_0002"])
        self.assertEqual(claims[0]["text"], shared)

    def test_determinism(self):
        self.assertEqual(extract_claims([ACADEMIC, INSTITUTIONAL], TOPIC),
                         extract_claims([ACADEMIC, INSTITUTIONAL], TOPIC))

    def test_dropped_sources_are_never_extracted(self):
        discovery = {
            "sources": [ACADEMIC],
            "dropped_sources": [{"source": dict(
                INSTITUTIONAL, source_id="src_0002",
                abstract="The Antikythera Mechanism contains 30 bronze "
                         "gear wheels."),
                "relevance_score": 10, "reasons": ["low_term_overlap"]}],
            "errors": [],
        }
        claims = extract_from_discovery(discovery, TOPIC)
        for claim in claims:
            self.assertNotIn("src_0002", claim["source_ids"])

    def test_extract_from_discovery_uses_kept_sources_only(self):
        discovery = {"sources": [ACADEMIC], "dropped_sources": []}
        self.assertEqual(extract_from_discovery(discovery, TOPIC),
                         extract_claims([ACADEMIC], TOPIC))
        self.assertEqual(extract_from_discovery({}, TOPIC), [])
        self.assertEqual(extract_from_discovery(None, TOPIC), [])


class ReviewPacketExtractionTests(unittest.TestCase):
    def test_packet_shows_extracted_candidates_unreviewed(self):
        claims = extract_claims([ACADEMIC], TOPIC)
        packet = build_packet(
            {"sources": [ACADEMIC], "warning": "Discovery only"},
            {"sources": [], "claims": []}, TOPIC, extracted_claims=claims)
        self.assertEqual(len(packet["extracted_claims"]), len(claims))
        for candidate in packet["extracted_claims"]:
            self.assertEqual(candidate["review_status"], "UNREVIEWED")
            self.assertFalse(candidate["include_in_script"])
        markdown = render_markdown(packet)
        self.assertIn("Extracted claim candidates", markdown)
        self.assertIn("candidates only", markdown)

    def test_packet_without_extraction_is_unchanged(self):
        packet = build_packet({"sources": [], "warning": "Discovery only"},
                              {"sources": [], "claims": []}, TOPIC)
        self.assertEqual(packet["extracted_claims"], [])
        self.assertEqual(packet["claim_review_template"]["text"], "")
        self.assertFalse(packet["claim_review_template"]["include_in_script"])


if __name__ == "__main__":
    unittest.main()
