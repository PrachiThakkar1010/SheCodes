from django.test import TestCase
from package_designer.compliance_rules_engine import (
    calculate_pdp_area,
    get_statutory_font_sizes,
    calculate_unit_sale_price,
    detect_allergens,
    validate_marketing_claims,
    compile_full_statutory_spec
)


class ComplianceRulesEngineTests(TestCase):

    def test_pdp_area_calculation_rectangular_box(self):
        # 10cm x 15cm x 5cm box -> largest face is 10 x 15 = 150 sq cm
        area = calculate_pdp_area('BOX', height_cm=15.0, width_cm=10.0, depth_cm=5.0)
        self.assertEqual(area, 150.0)

    def test_pdp_area_calculation_cylindrical(self):
        # Diameter 6cm, Height 15cm -> 40% of (pi * 6 * 15) = 0.40 * 282.743 = 113.10 sq cm
        area = calculate_pdp_area('CYLINDER', height_cm=15.0, width_cm=6.0, diameter_cm=6.0)
        self.assertAlmostEqual(area, 113.10, delta=0.5)

    def test_statutory_font_sizes_schedule_ii(self):
        # PDP area 150 sq cm (between 50 and 200 sq cm) -> Min general font: 2.0 mm
        # Net quantity 100g (between 50 and 200g) -> Min net qty numeral: 2.0 mm
        specs = get_statutory_font_sizes(pdp_area_sqcm=150.0, net_qty=100.0, qty_unit='g')
        self.assertEqual(specs['min_general_font_mm'], 2.0)
        self.assertEqual(specs['min_net_qty_numeral_mm'], 2.0)
        self.assertEqual(specs['veg_symbol']['square_side_mm'], 4.0)
        self.assertEqual(specs['veg_symbol']['circle_diameter_mm'], 2.0)

    def test_statutory_font_sizes_small_pack(self):
        # Small pack: PDP 30 sq cm (< 50) -> Min general font: 1.0 mm, net qty 40g -> 1.0 mm
        specs = get_statutory_font_sizes(pdp_area_sqcm=30.0, net_qty=40.0, qty_unit='g')
        self.assertEqual(specs['min_general_font_mm'], 1.0)
        self.assertEqual(specs['min_net_qty_numeral_mm'], 1.0)
        self.assertEqual(specs['veg_symbol']['square_side_mm'], 3.0)

    def test_unit_sale_price_under_1kg(self):
        # 250g pack with MRP Rs 100 -> USP per gram = 100/250 = Rs 0.40/g (Rs 40.00 / 100g)
        usp = calculate_unit_sale_price(mrp=100.0, net_qty=250.0, qty_unit='g')
        self.assertEqual(usp['per_unit_price'], 0.40)
        self.assertIn("0.40 / g", usp['usp_text'])
        self.assertIn("40.00 / 100g", usp['usp_text'])

    def test_unit_sale_price_over_1kg(self):
        # 2 kg pack with MRP Rs 500 -> USP per kg = Rs 250.00/kg
        usp = calculate_unit_sale_price(mrp=500.0, net_qty=2.0, qty_unit='kg')
        self.assertEqual(usp['per_unit_price'], 250.0)
        self.assertIn("250.00 / kg", usp['usp_text'])

    def test_allergen_detection(self):
        ingredients = "Refined Wheat Flour (Maida), Butter (Milk Fat), Almonds (Tree Nuts), Sugar, Emulsifier (INS 322 - Soya Lecithin)."
        res = detect_allergens(ingredients)
        self.assertTrue(res['mandatory_bolding_required'])
        detected = res['detected_allergens']
        self.assertTrue(any('Gluten' in a or 'Wheat' in a for a in detected))
        self.assertTrue(any('Milk' in a for a in detected))
        self.assertTrue(any('Tree Nuts' in a for a in detected))
        self.assertTrue(any('Soybeans' in a for a in detected))
        self.assertIn("CONTAINS:", res['statutory_advice_text'])

    def test_claims_validation_sugar_free(self):
        nutrition_compliant = {"sugars": 0.3}
        res_compliant = validate_marketing_claims("Sugar Free", nutrition_dict=nutrition_compliant)
        self.assertEqual(res_compliant[0]['status'], "COMPLIANT")

        nutrition_violating = {"sugars": 4.5}
        res_violating = validate_marketing_claims("Sugar Free", nutrition_dict=nutrition_violating)
        self.assertEqual(res_violating[0]['status'], "NON_COMPLIANT")

    def test_claims_validation_high_protein(self):
        nutrition_high = {"protein": 22.0}
        res_high = validate_marketing_claims("High Protein", nutrition_dict=nutrition_high)
        self.assertEqual(res_high[0]['status'], "COMPLIANT")

        nutrition_low = {"protein": 3.0}
        res_low = validate_marketing_claims("High Protein", nutrition_dict=nutrition_low)
        self.assertEqual(res_low[0]['status'], "NON_COMPLIANT")

    def test_compile_full_spec(self):
        project = {
            'pack_type': 'POUCH',
            'height_cm': 18.0,
            'width_cm': 12.0,
            'net_quantity': 200.0,
            'quantity_unit': 'g',
            'mrp': 150.0,
            'generic_product_name': 'Roasted Almonds',
            'brand_name': 'PureCraft',
            'diet_type': 'VEG',
            'ingredients': 'Almonds, Salt',
            'marketing_claims': 'High Protein'
        }
        spec = compile_full_statutory_spec(project)
        self.assertIn('pdp_calculations', spec)
        self.assertIn('usp_data', spec)
        self.assertIn('statutory_strings', spec)
        self.assertIn('panel_blueprints', spec)
        self.assertEqual(spec['statutory_strings']['mrp'], "MRP ₹ 150.00 (incl. of all taxes)")

