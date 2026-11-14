import unittest

from src.evidence import SCHEMA_VERSION, empty_ledger, migrate_ledger, validate_ledger
from src.source_types import SOURCE_TYPES, classify_source


class SourceTaxonomyTests(unittest.TestCase):
    def test_taxonomy_is_closed_and_expected(self):
        self.assertEqual(SOURCE_TYPES, {
            "primary", "archival", "official_record",
            "academic", "institutional", "other",
        })

    def test_provider_and_metadata_classification(self):
        self.assertEqual(classify_source({
            "provider": "Library of Congress",
            "url": "https://www.loc.gov/item/123",
        }), "archival")
        self.assertEqual(classify_source({
            "provider": "OpenAlex",
            "publication": "Journal of Ancient History",
            "work_type": "article",
            "url": "https://doi.org/10/example",
        }), "academic")
        self.assertEqual(classify_source({
            "url": "https://records.example.gov/report",
        }), "official_record")
        self.assertEqual(classify_source({
            "url": "https://unknown.example.org/item",
        }), "other")

    def test_explicit_valid_type_is_preserved(self):
        self.assertEqual(classify_source({"source_type": "primary"}), "primary")

    def test_legacy_secondary_is_conservatively_mapped(self):
        self.assertEqual(classify_source({"source_type": "secondary"}), "other")

    def test_empty_ledger_uses_schema_v2(self):
        self.assertEqual(empty_ledger()["schema_version"], SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, 2)

    def test_v1_migration_adds_types_without_changing_review_decisions(self):
        original = {
            "schema_version": 1,
            "claims": [{"claim_id": "c1", "status": "UNKNOWN"}],
            "sources": [{
                "source_id": "s1", "provider": "Internet Archive",
                "url": "https://archive.org/details/example",
                "review_status": "APPROVED", "notes": "Human checked",
            }],
        }
        migrated = migrate_ledger(original)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["sources"][0]["source_type"], "archival")
        self.assertEqual(migrated["sources"][0]["review_status"], "APPROVED")
        self.assertEqual(migrated["sources"][0]["notes"], "Human checked")
        self.assertEqual(original["schema_version"], 1)

    def test_v2_rejects_missing_or_unknown_source_type(self):
        ledger = {
            "schema_version": 2,
            "claims": [],
            "sources": [{"source_id": "s1"}, {"source_id": "s2", "source_type": "guess"}],
        }
        errors = validate_ledger(ledger)
        self.assertEqual(len([e for e in errors if "source_type" in e]), 2)

    def test_v2_accepts_taxonomy_values(self):
        ledger = {
            "schema_version": 2, "claims": [],
            "sources": [{"source_id": "s{}".format(i), "source_type": value}
                        for i, value in enumerate(sorted(SOURCE_TYPES))],
        }
        self.assertEqual(validate_ledger(ledger), [])

    def test_v1_is_not_valid_until_migrated(self):
        self.assertTrue(any("schema_version" in e for e in validate_ledger({
            "schema_version": 1, "claims": [], "sources": [],
        })))

    def test_unknown_future_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported evidence ledger schema_version"):
            migrate_ledger({"schema_version": 99, "claims": [], "sources": []})


if __name__ == "__main__":
    unittest.main()
