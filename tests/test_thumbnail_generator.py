"""Tests for the documentary thumbnail generator (src/thumbnail_generator).

Fixture-based only: synthetic PIL images, a small in-memory ledger.
No network, no real video files, no ComfyUI.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw

from src.thumbnail_generator import (
    BADGE_ZONE,
    HEIGHT,
    SAFE_MARGIN,
    WIDTH,
    append_thumbnail_qa,
    check_thumbnail_pro,
    draw_documentary_thumbnail,
    generate_documentary_thumbnails,
    generate_documentary_thumbnails_or_raise,
    pick_concepts,
    validate_headline,
)

LEDGER = {
    "topic": "The 2,000-Year-Old Object That Shouldn't Exist",
    "claims": [
        {"claim_id": "antikythera_01", "status": "KNOWN",
         "include_in_script": True, "shock_hook": True,
         "text": "A geared bronze machine that predicted eclipses existed "
                 "in the ancient world about two thousand years ago."},
        {"claim_id": "antikythera_09", "status": "KNOWN",
         "include_in_script": True,
         "text": "Nothing comparably complex appears again for about 1,400 "
                 "years, until the great clocks of medieval cathedrals."},
        {"claim_id": "antikythera_10", "status": "UNKNOWN",
         "include_in_script": True,
         "text": "No inscription on the mechanism names its builder, and no "
                 "ancient text describes the workshop that made it or the "
                 "person who paid for it."},
        {"claim_id": "antikythera_04", "status": "KNOWN",
         "include_in_script": True,
         "text": "What survives is 82 fragments containing 30 bronze gear wheels."},
    ],
    "sources": [],
}


def _fixture_image(path, size=(1600, 900)):
    """A non-blank synthetic image with a clear subject (gold gear-like
    circle on a dark navy field) so grading/vignette have something to
    work on."""
    img = Image.new("RGB", size, (13, 27, 48))
    draw = ImageDraw.Draw(img)
    draw.ellipse([size[0] // 2 - 220, size[1] // 2 - 220,
                  size[0] // 2 + 220, size[1] // 2 + 220],
                 fill=(212, 175, 55), outline=(255, 220, 120), width=12)
    for i in range(12):
        x = size[0] // 2 + int(260 * (1 if i % 2 == 0 else -1))
        draw.rectangle([x - 30, size[1] // 2 - 20, x + 30, size[1] // 2 + 20],
                       fill=(180, 140, 40))
    img.save(path)
    return path


class TestHeadlineValidation(unittest.TestCase):
    def test_grounded_headline_passes(self):
        ok, _ = validate_headline(
            "PREDICTED ECLIPSES", LEDGER["claims"][0]["text"])
        self.assertTrue(ok)

    def test_number_normalized(self):
        ok, _ = validate_headline(
            "NOTHING FOR 1,400 YEARS", LEDGER["claims"][1]["text"])
        self.assertTrue(ok)

    def test_interrogative_exempt_unknown_claim(self):
        ok, _ = validate_headline("WHO MADE IT?", LEDGER["claims"][2]["text"])
        self.assertTrue(ok)

    def test_misleading_word_refused(self):
        # "FORBIDDEN" appears in no ledger claim: must be refused.
        ok, reason = validate_headline(
            "THE FORBIDDEN MECHANISM", LEDGER["claims"][0]["text"])
        self.assertFalse(ok)
        self.assertIn("FORBIDDEN", reason)

    def test_too_few_words_refused(self):
        ok, _ = validate_headline("ECLIPSES", LEDGER["claims"][0]["text"])
        self.assertFalse(ok)

    def test_too_many_words_refused(self):
        ok, _ = validate_headline(
            "THE GEARED BRONZE MACHINE PREDICTED ECLIPSES",
            LEDGER["claims"][0]["text"])
        self.assertFalse(ok)

    def test_fabricated_amount_refused(self):
        ok, _ = validate_headline(
            "WORTH $1,000,000", LEDGER["claims"][0]["text"])
        self.assertFalse(ok)


class TestConceptPicking(unittest.TestCase):
    def test_picks_three_distinct_grounded_concepts(self):
        concepts = pick_concepts(LEDGER)
        self.assertEqual(len(concepts), 3)
        self.assertEqual(len({c["claim_id"] for c in concepts}), 3)
        self.assertEqual(len({c["headline"] for c in concepts}), 3)
        for concept in concepts:
            ok, _ = validate_headline(concept["headline"], concept["claim_text"])
            self.assertTrue(ok, concept["headline"])

    def test_concepts_cover_known_and_unknown(self):
        concepts = pick_concepts(LEDGER)
        tiers = {c["tier"] for c in concepts}
        self.assertIn("KNOWN", tiers)
        self.assertIn("UNKNOWN", tiers)

    def test_too_few_claims_yields_fewer_concepts(self):
        thin = {"claims": [LEDGER["claims"][0]], "sources": []}
        self.assertLess(len(pick_concepts(thin)), 3)


class TestDrawing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.image = _fixture_image(os.path.join(self.tmp, "focal.jpg"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_output_is_1280x720(self):
        out = os.path.join(self.tmp, "thumb.png")
        draw_documentary_thumbnail(
            Image.open(self.image), "PREDICTED ECLIPSES",
            LEDGER["claims"][0]["text"], out)
        with Image.open(out) as img:
            self.assertEqual(img.size, (WIDTH, HEIGHT))

    def test_headline_bbox_inside_safe_margins_and_badge_zone_clear(self):
        out = os.path.join(self.tmp, "thumb.png")
        spec = draw_documentary_thumbnail(
            Image.open(self.image), "NOTHING FOR 1,400 YEARS",
            LEDGER["claims"][1]["text"], out)
        hb = spec["headline_bbox"]
        self.assertGreaterEqual(hb[0], SAFE_MARGIN)
        self.assertGreaterEqual(hb[1], SAFE_MARGIN)
        self.assertLessEqual(hb[2], WIDTH - SAFE_MARGIN)
        self.assertLessEqual(hb[3], HEIGHT - SAFE_MARGIN)
        bx0, by0, _, _ = BADGE_ZONE
        self.assertTrue(hb[2] <= bx0 or hb[1] >= by0,
                        "headline enters the duration-badge zone")

    def test_refused_headline_raises(self):
        out = os.path.join(self.tmp, "thumb.png")
        with self.assertRaises(ValueError):
            draw_documentary_thumbnail(
                Image.open(self.image), "THE FORBIDDEN MECHANISM",
                LEDGER["claims"][0]["text"], out)
        self.assertFalse(os.path.exists(out))

    def test_different_focals_produce_different_images(self):
        out_c = os.path.join(self.tmp, "c.png")
        out_r = os.path.join(self.tmp, "r.png")
        draw_documentary_thumbnail(Image.open(self.image), "PREDICTED ECLIPSES",
                                   LEDGER["claims"][0]["text"], out_c, focal=0.5)
        draw_documentary_thumbnail(Image.open(self.image), "PREDICTED ECLIPSES",
                                   LEDGER["claims"][0]["text"], out_r, focal=0.9)
        with Image.open(out_c) as a, Image.open(out_r) as b:
            self.assertNotEqual(list(a.resize((32, 32)).getdata()),
                                list(b.resize((32, 32)).getdata()))

    def test_portrait_subject_in_upper_third_survives_crop(self):
        # Regression test for the museum-statue thumbnail: a portrait
        # source whose subject sits in the upper third must stay in
        # frame. A red marker band at 20-30% height must be visible
        # with focal_y=0.28 and absent with a centred crop.
        from src.thumbnail_generator import _fill_crop
        portrait = Image.new("RGB", (1080, 1920), (13, 27, 48))
        draw = ImageDraw.Draw(portrait)
        draw.rectangle([0, 384, 1080, 576], fill=(255, 0, 0))
        cropped = _fill_crop(portrait, WIDTH, HEIGHT, focal=0.5, focal_y=0.28)
        reds = sum(1 for r, g, b in cropped.getdata() if r > 200 and g < 80)
        self.assertGreater(reds, 1000, "upper-third subject lost in crop")
        centred = _fill_crop(portrait, WIDTH, HEIGHT, focal=0.5, focal_y=0.5)
        reds_centred = sum(1 for r, g, b in centred.getdata()
                           if r > 200 and g < 80)
        self.assertEqual(reds_centred, 0,
                         "centred crop unexpectedly kept the marker")


class TestQA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.image = _fixture_image(os.path.join(self.tmp, "focal.jpg"))
        self.out = os.path.join(self.tmp, "thumb.png")
        self.spec = draw_documentary_thumbnail(
            Image.open(self.image), "PREDICTED ECLIPSES",
            LEDGER["claims"][0]["text"], self.out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_qa_checks_pass_on_good_thumbnail(self):
        checks, overall = check_thumbnail_pro(
            self.out, "PREDICTED ECLIPSES", LEDGER["claims"][0]["text"],
            spec=self.spec)
        failed = [c for c in checks if c["status"] == "fail"]
        self.assertEqual(overall, "pass", failed)

    def test_qa_catches_wrong_size(self):
        small = os.path.join(self.tmp, "small.png")
        Image.open(self.out).resize((640, 360)).save(small)
        checks, overall = check_thumbnail_pro(
            small, "PREDICTED ECLIPSES", LEDGER["claims"][0]["text"],
            spec=self.spec)
        self.assertEqual(overall, "fail")
        failed = {c["check"] for c in checks if c["status"] == "fail"}
        self.assertIn("thumbnail_resolution", failed)

    def test_qa_catches_ledger_mismatch(self):
        checks, overall = check_thumbnail_pro(
            self.out, "THE FORBIDDEN MECHANISM",
            LEDGER["claims"][0]["text"], spec=self.spec)
        failed = {c["check"] for c in checks if c["status"] == "fail"}
        self.assertIn("thumbnail_claims_match_ledger", failed)

    def test_qa_catches_missing_file(self):
        checks, overall = check_thumbnail_pro(
            os.path.join(self.tmp, "nope.png"), "PREDICTED ECLIPSES",
            LEDGER["claims"][0]["text"])
        self.assertEqual(overall, "fail")


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.images = {
            "gears": _fixture_image(os.path.join(self.tmp, "gears.jpg")),
            "time": _fixture_image(os.path.join(self.tmp, "time.jpg")),
            "maker": _fixture_image(os.path.join(self.tmp, "maker.jpg")),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generates_three_variations_with_qa(self):
        outdir = os.path.join(self.tmp, "thumbs")
        results = generate_documentary_thumbnails_or_raise(
            LEDGER, LEDGER["topic"], "A 2,000-Year-Old Machine That Predicted Eclipses",
            outdir, "antikythera-short", image_paths=self.images)
        self.assertEqual(len(results), 3)
        self.assertEqual({r["variant"] for r in results}, {"a", "b", "c"})
        for result in results:
            self.assertTrue(os.path.exists(result["path"]))
            self.assertEqual(result["qa_overall"], "pass")
        qa_path = os.path.join(outdir, "thumbnails_qa.json")
        self.assertTrue(os.path.exists(qa_path))
        with open(qa_path, encoding="utf-8") as fh:
            qa = json.load(fh)
        self.assertEqual(qa["overall"], "pass")
        self.assertEqual(len(qa["variations"]), 3)

    def test_fail_soft_wrapper_never_raises(self):
        # No images, no video: generation cannot succeed, but the wrapper
        # must return [] instead of raising, so a video render survives.
        results = generate_documentary_thumbnails(
            {"claims": [], "sources": []}, "topic", "title",
            os.path.join(self.tmp, "out"), "slug")
        self.assertEqual(results, [])

    def test_fail_soft_wrapper_returns_empty_on_bad_ledger(self):
        results = generate_documentary_thumbnails(
            {"claims": [{"claim_id": "x", "status": "KNOWN", "text": "hi"}],
             "sources": []},
            "topic", "title", os.path.join(self.tmp, "out2"), "slug",
            image_paths=self.images)
        self.assertEqual(results, [])


class TestReportMerge(unittest.TestCase):
    def test_appends_checks_without_changing_video_verdict(self):
        tmp = tempfile.mkdtemp()
        try:
            report_path = os.path.join(tmp, "qa_report.json")
            report = {"video": "x.mp4", "overall": "pass",
                      "checks": [{"check": "file_exists", "status": "pass",
                                  "detail": "ok"}],
                      "fixes_applied": []}
            with open(report_path, "w", encoding="utf-8") as fh:
                json.dump(report, fh)
            results = [{
                "variant": "a",
                "qa_checks": [
                    {"check": "thumbnail_resolution", "status": "pass",
                     "detail": "1280x720"},
                    {"check": "thumbnail_claims_match_ledger", "status": "pass",
                     "detail": "ok"}],
            }]
            self.assertTrue(append_thumbnail_qa(report_path, results))
            with open(report_path, encoding="utf-8") as fh:
                merged = json.load(fh)
            self.assertEqual(merged["overall"], "pass")
            names = [c["check"] for c in merged["checks"]]
            self.assertIn("thumbnail_a_thumbnail_resolution", names)
            self.assertIn("thumbnail_a_thumbnail_claims_match_ledger", names)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_merge_skips_missing_report(self):
        self.assertFalse(append_thumbnail_qa(
            "/nonexistent/qa_report.json",
            [{"variant": "a", "qa_checks": []}]))


if __name__ == "__main__":
    unittest.main()
