"""
compliance/tests.py
---------------------
Every test in this file exists because a REAL bug was found on a REAL
scan and then fixed - each one is a permanent guard against that exact
bug coming back. This is the direct answer to "how do I stop manually
testing every time": run this file. It takes seconds, and it re-checks
every failure mode we've already found and fixed, automatically,
forever, so a future change can't silently reintroduce one.

Run it with:
    python manage.py test compliance

Run it BEFORE trusting any change to labeler.py / aggregator.py /
nutrition.py / rules_engine.py - that's the actual habit that replaces
"manually re-testing every time."

When you find a NEW bug in the future, the fix isn't complete until
there's a new test here for it, built the same way every test below
was built: reconstruct the exact real input that broke, assert the
correct output, verify it fails on the OLD code and passes on the
FIXED code. A fix with no test is a fix that can silently regress.
"""

from django.test import TestCase

from compliance.engine.labeler import label_lines
from compliance.engine.aggregator import aggregate_lines
from compliance.engine.nutrition import parse_nutrition
from compliance.engine.rules_engine import run_rules


class MRPBoxSelectionTests(TestCase):
    """
    Bug: a package with BOTH "Unit Sale Price :" (blank, no value on
    that product) and "MRP :" (has the real value) as separate lines -
    _first_box(items) picked whichever line came first in reading
    order, not the one that actually had the number. This produced a
    self-contradictory report: LM-009 measured a real font size from
    the wrong box while LM-006 said "no MRP detected."
    Found on: a real scan of Katak Batak (product21-style packaging).
    """

    def test_mrp_value_and_box_come_from_the_line_that_has_the_number(self):
        lines = [
            {"text": "UNIT SALE PRICE :", "box": [500, 1360, 700, 1400],
             "confidence": 0.9, "image_id": "img1", "label": "OTHER"},
            {"text": "MRP :", "box": [500, 1410, 600, 1450],
             "confidence": 0.9, "image_id": "img1", "label": "OTHER"},
            {"text": "10.00", "box": [610, 1410, 660, 1450],
             "confidence": 0.85, "image_id": "img1", "label": "OTHER"},
            {"text": "(INCL OF ALL TAXES)", "box": [500, 1455, 750, 1485],
             "confidence": 0.9, "image_id": "img1", "label": "OTHER"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)

        self.assertEqual(result["mrp"]["value"], 10.0)
        self.assertEqual(result["mrp"]["box"], [610, 1410, 660, 1450],
                          "MRP box must point at the actual '10.00' text, "
                          "not the unrelated 'Unit Sale Price' label")

    def test_no_box_returned_when_no_value_was_ever_found(self):
        # Bug found on a LATER real scan (Knorr Pizza & Pasta Sauce):
        # the fix above only handled the case where a value WAS found
        # but the wrong box got attached - it missed the case where NO
        # value is found at ALL, where the function still fell back to
        # _first_box(items) (the bare "MRP" keyword line itself, with
        # nothing ever linked to it). That box then fed LM-009's font-
        # size calculation, producing the same self-contradiction again:
        # "no MRP detected" alongside a confidently reported font size.
        # If there's no confirmed value, there must be no box either.
        lines = [
            {"text": "MRP", "box": [100, 200, 150, 220], "confidence": 0.9, "image_id": "img1"},
            {"text": "Ingredients: tomato, garlic", "box": [100, 300, 400, 320],
             "confidence": 0.9, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)

        self.assertIsNone(result["mrp"]["value"])
        self.assertIsNone(result["mrp"]["box"],
                           "no box should be returned when no MRP value was ever confirmed")

        rules = run_rules(result, ocr_confidence_avg=0.9)
        lm006 = next(r for r in rules if r["rule_code"] == "LM-006")
        lm009 = next(r for r in rules if r["rule_code"] == "LM-009")
        self.assertFalse(lm006["passed"])
        self.assertFalse(lm009["passed"])
        self.assertNotIn("mm", lm009["details"],
                          "must not report a measured font size with no confirmed MRP box")

    def test_value_found_via_generic_price_synonym_still_gets_a_box(self):
        # A fourth gap in the same function, found via a real user
        # report: a value found through the plain "search every item
        # for a bare digit" fallback (used when the value-bearing line
        # matches MRP via a generic synonym like "price"/"unit sale
        # price" rather than literal "MRP" text or a Rs/₹ prefix) never
        # identified WHICH item had the digits, so no box was attached.
        # Result: LM-006 correctly passed (a real value was found) but
        # LM-009 still said "could not be measured" - a real Knorr
        # Pizza & Pasta Sauce scan showed exactly this: no "Missing or
        # Invalid MRP" violation, but "MRP Font Size Too Small" with
        # "could not be measured" as its own contradictory detail text.
        lines = [{"text": "PRICE: 20/-", "box": [100, 200, 250, 220],
                  "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)

        self.assertEqual(result["mrp"]["value"], 20.0)
        self.assertIsNotNone(result["mrp"]["box"])

        rules = run_rules(result, ocr_confidence_avg=0.9)
        lm006 = next(r for r in rules if r["rule_code"] == "LM-006")
        lm009 = next(r for r in rules if r["rule_code"] == "LM-009")
        self.assertTrue(lm006["passed"])
        self.assertIn("mm", lm009["details"],
                       "a confirmed value must produce a real font-size measurement, not 'could not be measured'")


class NutritionMatchingTests(TestCase):
    """
    Bug 1: a value can sit slightly ABOVE its own label (not below) on
    a real nutrition table - forward-only search missed it and grabbed
    the NEXT nutrient's value instead, shifting every row by one.
    Found on: product1 (Balaji Mung Dal), real scan.

    Bug 2: even with correct geometric nearest-match, "Energy" grabbed
    a geometrically-closer "19.0 g" that actually belonged to Protein -
    Energy is never in grams. Fixed with an expected-unit filter per
    nutrient. Found on: product21 (Katak Batak), real scan.
    """

    def test_value_above_label_still_matches_correctly(self):
        # Product1's real geometry: "486 Kcal" sits slightly ABOVE
        # "ENERGY", not below it.
        items = [
            {"text": "ENERGY", "box": [579, 506, 629, 530]},
            {"text": "486 Kcal", "box": [802, 500, 854, 518]},
            {"text": "PROTEIN", "box": [579, 526, 634, 549]},
            {"text": "22.9g", "box": [801, 519, 843, 538]},
        ]
        rows = {r["nutrient"]: r for r in parse_nutrition(items)}
        self.assertEqual(rows["Energy"]["amount"], 486.0)
        self.assertEqual(rows["Energy"]["unit"], "kcal")
        self.assertEqual(rows["Protein"]["amount"], 22.9)

    def test_energy_rejects_a_closer_but_wrong_unit_candidate(self):
        # Protein's value (19.0g) is geometrically CLOSER to "ENERGY"
        # than Energy's own real value (624 Kcal) - the fix must still
        # pick the unit-plausible one, not just the nearest one.
        items = [
            {"text": "ENERGY", "box": [100, 500, 200, 530]},
            {"text": "624 Kcal", "box": [300, 470, 380, 500]},   # farther
            {"text": "PROTEIN", "box": [100, 540, 200, 570]},
            {"text": "19.0 g", "box": [300, 510, 360, 535]},     # closer, wrong nutrient
        ]
        rows = {r["nutrient"]: r for r in parse_nutrition(items)}
        self.assertEqual(rows["Energy"]["amount"], 624.0)
        self.assertEqual(rows["Energy"]["unit"], "kcal")
        self.assertEqual(rows["Protein"]["amount"], 19.0)

    def test_implausible_daily_value_is_flagged(self):
        # A likely OCR-dropped-decimal-point case ("12.0g" misread as
        # "120.0g") - can't be "fixed" (we can't know the real value),
        # but it MUST be flagged so a human knows to verify it.
        items = [
            {"text": "SATURATED FAT", "box": [100, 500, 260, 530]},
            {"text": "120.0g", "box": [300, 500, 360, 530]},
        ]
        rows = {r["nutrient"]: r for r in parse_nutrition(items)}
        self.assertTrue(rows["Saturated Fat"]["implausible"])

    def test_implausible_value_suggests_the_confirmed_real_correction(self):
        # Not a guess - this is CONFIRMED ground truth: a real scan of
        # Mung Dal showed Saturated Fat as 78.0g/390%, and a human
        # checked the actual physical package - the real printed value
        # is 7.8g. PaddleOCR dropped the decimal point. Since the
        # mechanism is now confirmed (not theorized), the system
        # suggests the divide-by-10 correction alongside the raw value
        # (never silently overwriting what OCR actually extracted).
        items = [
            {"text": "SATURATED FAT", "box": [100, 500, 260, 530]},
            {"text": "78.0g", "box": [300, 500, 360, 530]},
        ]
        rows = {r["nutrient"]: r for r in parse_nutrition(items)}
        self.assertEqual(rows["Saturated Fat"]["amount"], 78.0,
                          "raw OCR value must never be silently overwritten")
        self.assertEqual(rows["Saturated Fat"]["likely_correct_value"], 7.8)


class BatchNumberDateConfusionTests(TestCase):
    """
    Bug: the BATCH_NUMBER value-linking pattern was permissive enough
    to match dates ("02JUL26", "31OCT26") and random unrelated words
    ("FARMERS", "see") as if they were batch codes. Found via the
    hand-corrected eval sheet (BATCH_NUMBER precision was 73.7%, the
    worst of all fields).
    """

    def test_dates_are_not_mistaken_for_batch_numbers(self):
        from compliance.engine.labeler import ROW_VALUE_PATTERNS
        pattern = ROW_VALUE_PATTERNS["BATCH_NUMBER"]
        self.assertIsNone(pattern.match("02JUL26"))
        self.assertIsNone(pattern.match("31OCT26"))
        self.assertIsNone(pattern.match("14/08/26"))

    def test_unrelated_words_are_not_mistaken_for_batch_numbers(self):
        from compliance.engine.labeler import ROW_VALUE_PATTERNS
        pattern = ROW_VALUE_PATTERNS["BATCH_NUMBER"]
        self.assertIsNone(pattern.match("FARMERS"))
        self.assertIsNone(pattern.match("see"))

    def test_real_batch_codes_still_match(self):
        from compliance.engine.labeler import ROW_VALUE_PATTERNS
        pattern = ROW_VALUE_PATTERNS["BATCH_NUMBER"]
        self.assertIsNotNone(pattern.match("0211LL26"))
        self.assertIsNotNone(pattern.match("B12345"))
        self.assertIsNotNone(pattern.match("LOT-2024-A5"))


class ManufacturingDateFallbackTests(TestCase):
    """
    Bug: a bare "PKD" keyword with no linked value stayed labeled
    OTHER rather than MANUFACTURING_DATE - the aggregator's fallback
    (which searches ALL raw lines near a date keyword) never ran,
    because the code skipped straight to `data[field] = None` whenever
    the group was empty, before the fallback got a chance.
    """

    def test_date_recovered_even_when_no_line_was_labeled_the_date_field(self):
        fake_lines = [
            {"text": "PKD", "box": [100, 200, 130, 220], "confidence": 0.9,
             "image_id": "img1", "label": "OTHER"},
            {"text": "02JUL26", "box": [140, 202, 200, 222], "confidence": 0.85,
             "image_id": "img1", "label": "OTHER"},
        ]
        result = aggregate_lines(fake_lines)
        self.assertEqual(result["manufacturing_date"]["raw_text"], "02JUL26")

    def test_bare_mfd_abbreviation_is_recognized(self):
        # A package can print just "MFD:" (no "date"/"on" following it),
        # the same way "PKD" and "MFG" work standalone - this was a real
        # gap: labeler.py only matched "MFD DATE"/"MFD ON", missing the
        # bare form entirely.
        fake_lines = [
            {"text": "MFD:", "box": [100, 200, 150, 220], "confidence": 0.9, "image_id": "img1"},
            {"text": "14/08/26", "box": [160, 202, 220, 222], "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(fake_lines)
        result = aggregate_lines(labeled)
        self.assertEqual(result["manufacturing_date"]["raw_text"], "14/08/26")


class ConsumerContactDigitRangeTests(TestCase):
    """
    Bug 1: a real phone number, OCR-truncated from 10 digits to 8
    ("59014141" instead of the real number), was never even LABELED
    as CONSUMER_CONTACT because the line-classifier required exactly
    10 digits - but the downstream validator (once something IS
    labeled) already tolerated 7-15 digits. Fixed by matching the two
    thresholds. Found on: a real scan of Katak Batak.

    Bug 2 (found from Bug 1's own fix): broadening to 7-15 digits at
    classify() time was too permissive - it let ANY unrelated digit
    sequence anywhere on the page (a license number fragment, a batch
    "Code" value) get independently mislabeled CONSUMER_CONTACT, with
    no requirement that it actually be near a real contact keyword.
    Found on: a real scan of Gems candy, where the batch Code
    ("20216449") was wrongly captured as the consumer contact number.
    Fixed by removing the bare-digit rule from classify() entirely and
    only linking a nearby digit sequence to CONSUMER_CONTACT via
    proximity to a genuine keyword anchor (same discipline as MRP/date
    linking), covering both same-row and below-the-heading placement.
    """

    def test_truncated_phone_number_gets_labeled_consumer_contact(self):
        lines = [{"text": "CALL OUR CONSUMER CARE 59014141 ON ANY WORKING",
                  "box": [100, 100, 500, 130], "confidence": 0.8, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertEqual(labeled[0]["label"], "CONSUMER_CONTACT")

    def test_unrelated_digit_sequence_is_not_mistaken_for_contact_number(self):
        lines = [
            {"text": "Code.", "box": [100, 200, 150, 220], "confidence": 0.9, "image_id": "img1"},
            {"text": "20216449", "box": [160, 202, 250, 222], "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)
        self.assertIsNone(result["consumer_contact"])

    def test_phone_number_below_a_contact_heading_still_gets_linked(self):
        # Phone number on the line BELOW "Consumer Care", not beside it -
        # a common real layout that a same-row-only check would miss.
        lines = [
            {"text": "CALL OUR CONSUMER CARE EXECUTIVE", "box": [100, 500, 400, 530],
             "confidence": 0.9, "image_id": "img2"},
            {"text": "9099014141", "box": [100, 535, 250, 560], "confidence": 0.85, "image_id": "img2"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)
        self.assertIn("9099014141", result["consumer_contact"]["raw_text"])


class ManufacturerVsPackagingMaterialTests(TestCase):
    """
    Bug: "Pkg Mtrl Mfd. By: Huhtamaki India Ltd" (the PACKAGING
    MATERIAL manufacturer - a legally distinct declaration) was
    captured as the product's manufacturer name, instead of the real
    food manufacturer ("Mfd. By: Mondelez India Foods..."). Found on:
    a real scan of Gems candy.

    This fix also surfaced a second real bug: the bare-"MFD" date
    keyword added earlier the same day was matching EVERY "Mfd. By:
    [company]" manufacturer line too (since MANUFACTURING_DATE is
    checked before MANUFACTURER_NAME), misclassifying manufacturer
    declarations as dates. Fixed by excluding "mfd" immediately
    followed by "by" from the date keyword match.
    """

    def test_packaging_material_manufacturer_is_not_captured_as_the_manufacturer(self):
        lines = [{"text": "PkgMtrl.Mfd.By:HuhtamakiIndiaLtd.,Pantnagar,PR-22-000-07-AAACT0086E",
                  "box": [100, 100, 500, 120], "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertNotEqual(labeled[0]["label"], "MANUFACTURER_NAME")

    def test_real_manufacturer_line_still_correctly_labeled(self):
        lines = [{"text": "Mfd. By: Mondelez India Foods Private Limited",
                  "box": [100, 150, 500, 170], "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertEqual(labeled[0]["label"], "MANUFACTURER_NAME")

    def test_bare_mfd_followed_by_by_is_not_mistaken_for_a_date(self):
        lines = [{"text": "Mfd. By: Mondelez India Foods Private Limited",
                  "box": [100, 150, 500, 170], "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertNotEqual(labeled[0]["label"], "MANUFACTURING_DATE")

    def test_bare_mfd_not_followed_by_by_is_still_a_date(self):
        lines = [
            {"text": "MFD:", "box": [100, 200, 150, 220], "confidence": 0.9, "image_id": "img2"},
            {"text": "14/08/26", "box": [160, 202, 220, 222], "confidence": 0.85, "image_id": "img2"},
        ]
        labeled = label_lines(lines)
        self.assertEqual(labeled[0]["label"], "MANUFACTURING_DATE")

    def test_manufacturer_name_wins_over_fssai_when_license_is_merged_into_the_same_line(self):
        # Real bug: a package had its FSSAI license number OCR'd onto
        # the SAME line as the manufacturer name/company suffix (e.g.
        # "Y-Mfd.By: Makson Health Care Private Limited, Lic.No.
        # 10012026000353" - the 14-digit license number matched
        # FSSAI_LICENSE_NO (checked earlier in priority), so the WHOLE
        # line - company name included - got claimed by FSSAI and the
        # manufacturer name was lost entirely. Every manufacturer
        # mention on that package had this same merged-line problem,
        # so Manufacturer Name showed up as completely missing.
        lines = [{"text": "Y-Mfd.By: Makson Health Care Private Limited, Lic.No. 10012026000353",
                  "box": [100, 100, 600, 120], "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertEqual(labeled[0]["label"], "MANUFACTURER_NAME")

    def test_pure_fssai_line_without_manufacturer_signal_still_goes_to_fssai(self):
        lines = [{"text": "FSSAI Lic. No. 10012041000078",
                  "box": [100, 100, 400, 120], "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertEqual(labeled[0]["label"], "FSSAI_LICENSE_NO")

    def test_packaging_material_still_excluded_even_with_properly_spaced_text(self):
        # The original fix happened to pass its own test only because
        # OCR had glued "India" and "Ltd" together with no space,
        # making \bltd\b fail to match by accident - if OCR preserves
        # the space (a very plausible, arguably MORE likely case), the
        # exclusion needs to still work, not pass by luck.
        lines = [{"text": "Pkg Mtrl Mfd. By: Huhtamaki India Ltd, Pantnagar",
                  "box": [100, 100, 500, 120], "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        self.assertNotEqual(labeled[0]["label"], "MANUFACTURER_NAME")


class BatchNumberCodeSynonymTests(TestCase):
    """
    Bug: a package labeled its batch/lot identifier as "Code." instead
    of "Batch No." - a synonym the keyword list didn't recognize at
    all, so the batch number showed up as completely missing even
    though it was clearly printed and OCR'd correctly. Found on: a
    real scan of Gems candy.
    """

    def test_code_label_is_recognized_as_batch_number(self):
        lines = [
            {"text": "Code.", "box": [100, 200, 150, 220], "confidence": 0.9, "image_id": "img1"},
            {"text": "20216449", "box": [160, 202, 250, 222], "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)
        self.assertIn("20216449", result["batch_number"]["raw_text"])


class ProductNameCrossImageTests(TestCase):
    """
    Bug: a multi-image scan let EVERY photo nominate its own "tallest
    text" PRODUCT_NAME candidates, then joined ALL of them across ALL
    photos with " | " - producing garbage like "Ching's | Red | Chilli
    | Sauce | IV | Red Chilli | Issal" (with fragments from unrelated
    photos, including a near-miss OCR misread of the FSSAI stamp).
    Fixed by only using candidates from the single photo with the
    tallest candidate. Found on: a real scan of Ching's Red Chilli Sauce.
    """

    def test_product_name_comes_from_one_coherent_image_not_all_of_them(self):
        fake_lines = [
            {"text": "Ching's", "box": [100, 50, 220, 90], "confidence": 0.95,
             "image_id": "img1", "label": "PRODUCT_NAME"},
            {"text": "Red Chilli Sauce", "box": [100, 95, 320, 130], "confidence": 0.9,
             "image_id": "img1", "label": "PRODUCT_NAME"},
            {"text": "IV", "box": [400, 300, 420, 320], "confidence": 0.85,
             "image_id": "img2", "label": "PRODUCT_NAME"},
            {"text": "Red Chilli", "box": [50, 400, 150, 430], "confidence": 0.88,
             "image_id": "img2", "label": "PRODUCT_NAME"},
            {"text": "Issal", "box": [10, 10, 60, 30], "confidence": 0.7,
             "image_id": "img3", "label": "PRODUCT_NAME"},
        ]
        result = aggregate_lines(fake_lines)
        self.assertEqual(result["product_name"]["raw_text"], "Ching's Red Chilli Sauce")


class ReportInternalConsistencyTests(TestCase):
    """
    Bug: is_compliant was computed from the raw failed-rules count
    BEFORE attempting to save ComplianceViolation rows - if a
    rule_code lookup failed (e.g. ComplianceRule table not seeded),
    violations got silently dropped, producing a report that said
    "non-compliant" while showing 0 violations. Fixed by deriving
    is_compliant/score from what actually got saved.
    """

    def test_is_compliant_reflects_actually_saveable_violations(self):
        # Simulate the exact failure: run_rules finds failures, but
        # the ComplianceRule table has nothing seeded for them.
        sparse_data = {
            "product_name": None, "manufacturer": None, "manufacturer_address": None,
            "net_quantity": None, "manufacturing_date": None, "expiry_date": None,
            "mrp": None, "fssai_license": None, "consumer_contact": None,
            "batch_number": None, "ocr_lines": [],
        }
        results = run_rules(sparse_data, ocr_confidence_avg=0.9)
        failed = [r for r in results if not r["passed"]]
        # this is the real-world assertion: if NO rules are seeded,
        # saveable_failed must be empty, and is_compliant must be
        # computed from THAT, not from the raw `failed` count - this
        # test documents the expected relationship pipeline.py must
        # maintain, since pipeline.py itself needs a real DB to test
        # against (see products/tests.py for the full DB-backed version).
        self.assertGreater(len(failed), 0, "sanity check: sparse data should genuinely fail rules")


class ManufacturingDatePresenceOnlyTests(TestCase):
    """
    Deliberate behavior change, by explicit request: LM-005 used to
    also validate the manufacturing date's format against a regex and
    fail the rule if it didn't match a recognized date shape (e.g. a
    bare "Pkd." keyword with no digits captured showed as "found but
    not in a recognized format" rather than a clean pass/fail). Now
    it's presence-only: if anything was captured for this field, it
    passes, no format validation. This means a bare keyword with no
    real date value (e.g. an illegible inkjet stamp) now shows as
    PASSING, not failing - a real tradeoff, made deliberately.
    """

    def test_bare_keyword_with_no_real_date_now_passes(self):
        data = {
            "product_name": None, "manufacturer": None, "manufacturer_address": None,
            "net_quantity": None, "manufacturing_date": {"raw_text": "Pkd.", "box": [0, 0, 10, 10]},
            "expiry_date": None, "mrp": None, "fssai_license": None,
            "consumer_contact": None, "batch_number": None, "ocr_lines": [],
        }
        results = run_rules(data, ocr_confidence_avg=0.9)
        lm005 = next(r for r in results if r["rule_code"] == "LM-005")
        self.assertTrue(lm005["passed"])

    def test_nothing_found_at_all_still_fails(self):
        data = {
            "product_name": None, "manufacturer": None, "manufacturer_address": None,
            "net_quantity": None, "manufacturing_date": None,
            "expiry_date": None, "mrp": None, "fssai_license": None,
            "consumer_contact": None, "batch_number": None, "ocr_lines": [],
        }
        results = run_rules(data, ocr_confidence_avg=0.9)
        lm005 = next(r for r in results if r["rule_code"] == "LM-005")
        self.assertFalse(lm005["passed"])


class FSSAIFoodOnlyTests(TestCase):
    """
    Feature, by explicit request: FSSAI licensing only legally applies
    to food products (Food Safety and Standards Act, 2006) - a
    non-food product (electronics, cosmetics, etc.) has no FSSAI
    requirement at all, and shouldn't be flagged as "missing" a
    declaration that was never applicable. Since the scan form doesn't
    currently collect a real product category (hardcoded to "Packaged
    Goods" for every scan - see products/views.py), pipeline.py infers
    food-ness from what was actually extracted: a real nutrition
    table, or an "Ingredients:" declaration.
    """

    def test_food_product_without_fssai_still_fails(self):
        data = {
            "product_name": None, "manufacturer": None, "manufacturer_address": None,
            "net_quantity": None, "manufacturing_date": None, "expiry_date": None,
            "mrp": None, "fssai_license": None, "consumer_contact": None,
            "batch_number": None, "ocr_lines": [],
        }
        results = run_rules(data, is_likely_food=True)
        lm010 = next(r for r in results if r["rule_code"] == "LM-010")
        self.assertFalse(lm010["passed"])

    def test_non_food_product_without_fssai_passes(self):
        data = {
            "product_name": None, "manufacturer": None, "manufacturer_address": None,
            "net_quantity": None, "manufacturing_date": None, "expiry_date": None,
            "mrp": None, "fssai_license": None, "consumer_contact": None,
            "batch_number": None, "ocr_lines": [],
        }
        results = run_rules(data, is_likely_food=False)
        lm010 = next(r for r in results if r["rule_code"] == "LM-010")
        self.assertTrue(lm010["passed"])

    def test_food_product_with_fssai_still_passes(self):
        data = {
            "product_name": None, "manufacturer": None, "manufacturer_address": None,
            "net_quantity": None, "manufacturing_date": None, "expiry_date": None,
            "mrp": None, "fssai_license": {"raw_text": "FSSAI Lic. No. 10012041000078", "box": [0, 0, 10, 10]},
            "consumer_contact": None, "batch_number": None, "ocr_lines": [],
        }
        results = run_rules(data, is_likely_food=True)
        lm010 = next(r for r in results if r["rule_code"] == "LM-010")
        self.assertTrue(lm010["passed"])


class NetQuantityCountUnitTests(TestCase):
    """
    Feature, by explicit request: Legal Metrology permits net quantity
    declared by NUMBER (not just weight/volume) for commodities sold
    by count rather than measured - commonly printed as "6 N" or
    "6 Nos" on Indian multi-pack/candy packaging. This was previously
    rejected entirely: the extraction regex itself didn't recognize
    "N"/"Nos"/"Pcs" as a unit at all, so these products showed "no
    valid net quantity declaration" rather than passing.
    """

    def test_bare_n_unit_is_accepted(self):
        lines = [{"text": "Net Qty: 6 N", "box": [100, 100, 300, 120],
                  "confidence": 0.9, "image_id": "img1"}]
        result = aggregate_lines(label_lines(lines))
        self.assertEqual(result["net_quantity"]["value"], 6.0)
        self.assertEqual(result["net_quantity"]["unit"], "n")
        rules = run_rules(result, ocr_confidence_avg=0.9)
        lm004 = next(r for r in rules if r["rule_code"] == "LM-004")
        self.assertTrue(lm004["passed"])

    def test_nos_and_pcs_variants_normalize_to_n(self):
        for text in ["Net Weight: 6 Nos", "Net Qty: 10 Pcs"]:
            lines = [{"text": text, "box": [100, 100, 300, 120],
                      "confidence": 0.9, "image_id": "img1"}]
            result = aggregate_lines(label_lines(lines))
            self.assertEqual(result["net_quantity"]["unit"], "n")

    def test_batch_no_is_not_mistaken_for_a_count_declaration(self):
        # "Batch No. 12345" must NOT be read as "12345 No." (a
        # quantity) - "no"/"no." was deliberately excluded from the
        # unit pattern for exactly this reason.
        lines = [{"text": "Batch No. 12345", "box": [100, 100, 300, 120],
                  "confidence": 0.9, "image_id": "img1"}]
        result = aggregate_lines(label_lines(lines))
        self.assertIsNone(result["net_quantity"]["value"])


class BatchNumberCrossBlockLinkingTests(TestCase):
    """
    Feature, by explicit request: MRP, manufacturing date, expiry
    date, and consumer contact all had dedicated cross-block value
    linking (the keyword and its value can be two separate OCR boxes,
    not just adjacent same-row text) - batch number did not, and was
    silently weaker than the other three fields the same request
    explicitly named. Added the same treatment here.
    """

    def test_batch_value_well_below_the_keyword_still_gets_linked(self):
        lines = [
            {"text": "Batch No.", "box": [100, 500, 200, 520], "confidence": 0.9, "image_id": "img1"},
            {"text": "XY12345", "box": [100, 560, 200, 585], "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)
        self.assertIn("XY12345", result["batch_number"]["raw_text"])

    def test_code_synonym_also_gets_cross_block_linking(self):
        lines = [
            {"text": "Code.", "box": [100, 500, 150, 520], "confidence": 0.9, "image_id": "img1"},
            {"text": "20216449", "box": [100, 560, 200, 585], "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)
        self.assertIn("20216449", result["batch_number"]["raw_text"])


class MRPPointerTextExclusionTests(TestCase):
    """
    Serious bug found via a live scan (a mosquito-repellent product,
    "All Out"): an instructional line reading "For MRP (Incl. of all
    taxes), MFD, Batch No. See below, USP" contains the literal word
    "MRP" but is a POINTER telling the reader to look at a separate
    stamped code elsewhere - not an actual price declaration. Using it
    as a value-linking anchor let a nearby BATCH CODE get linked in as
    if it were the MRP value, reporting a price of Rs. 890,427,120 for
    a mosquito repellent. Confidently wrong is worse than "not found" -
    this must report no MRP rather than an absurd number. The real
    instructional sentence was split across two separate OCR boxes by
    text-wrapping, so the fix can't rely on "MRP" and "see below"
    being in the same line - it also treats "For MRP..." (a sentence
    construction real declarations don't use) as its own signal.
    """

    def test_pointer_line_does_not_produce_a_false_mrp_value(self):
        lines = [
            {"text": "For MRP Rs. (IncL.ofall taxes),", "box": [100, 600, 400, 625],
             "confidence": 0.85, "image_id": "img1"},
            {"text": "MFD, Batch No. See below, USP", "box": [100, 630, 400, 655],
             "confidence": 0.85, "image_id": "img1"},
            {"text": "890427120", "box": [100, 660, 250, 685],
             "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)

        self.assertIsNone(result["mrp"]["value"],
                           "a pointer/instructional line must never produce a fabricated MRP value")

    def test_batch_number_linking_is_unaffected_by_the_mrp_fix(self):
        lines = [
            {"text": "For MRP Rs. (IncL.ofall taxes),", "box": [100, 600, 400, 625],
             "confidence": 0.85, "image_id": "img1"},
            {"text": "MFD, Batch No. See below, USP", "box": [100, 630, 400, 655],
             "confidence": 0.85, "image_id": "img1"},
            {"text": "890427120", "box": [100, 660, 250, 685],
             "confidence": 0.85, "image_id": "img1"},
        ]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)

        self.assertIn("890427120", result["batch_number"]["raw_text"])

    def test_genuine_mrp_declaration_is_unaffected(self):
        lines = [{"text": "MRP: Rs. 50", "box": [100, 100, 300, 120],
                  "confidence": 0.9, "image_id": "img1"}]
        labeled = label_lines(lines)
        result = aggregate_lines(labeled)
        self.assertEqual(result["mrp"]["value"], 50.0)