"""
Run once (and safely re-run any time - it upserts by rule_code):

    python manage.py seed_rules

Populates ComplianceRule with the rule set compliance/engine/rules_engine.py
checks against. Title = the short violation heading shown on the report
(e.g. "MRP Font Size Too Small"). Description = the fixed rule citation
shown in the report's "Violated Rule" box. rule_code must match the codes
used in rules_engine.py's add(code, ...) calls.
"""

from django.core.management.base import BaseCommand
from compliance.models import ComplianceRule

RULES = [
    dict(rule_code="LM-001", severity="HIGH",
         title="Missing Manufacturer Name",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(a): "
                      "Mandatory declaration of the manufacturer's or packer's name."),
    dict(rule_code="LM-002", severity="HIGH",
         title="Missing Manufacturer Address",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(a): "
                      "Mandatory declaration of manufacturer's name and complete address."),
    dict(rule_code="LM-003", severity="HIGH",
         title="Missing Product Identity",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(b): "
                      "Mandatory declaration of the common or generic name of the commodity."),
    dict(rule_code="LM-004", severity="HIGH",
         title="Net Quantity Not in Standard Unit",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(b): "
                      "Net quantity must be declared in exact standard units (grams, millilitres, etc.), "
                      "not approximated."),
    dict(rule_code="LM-005", severity="MEDIUM",
         title="Missing or Invalid Manufacturing Date",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(c): "
                      "Mandatory declaration of the month and year in which the commodity was "
                      "manufactured or packed."),
    dict(rule_code="LM-006", severity="HIGH",
         title="Missing or Invalid MRP",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(e): "
                      "Mandatory declaration of the retail sale price (MRP) of the package."),
    dict(rule_code="LM-007", severity="MEDIUM",
         title="MRP Missing Tax-Inclusion Wording",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(e), "
                      "Explanation: The retail sale price declaration must state that it is inclusive "
                      "of all taxes."),
    dict(rule_code="LM-008", severity="MEDIUM",
         title="Missing Consumer Complaint Contact",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(f): "
                      "Mandatory declaration of the name, address, telephone number and/or e-mail "
                      "address of a person or office to contact in case of consumer complaints."),
    dict(rule_code="LM-009", severity="HIGH",
         title="MRP Font Size Too Small",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(f): "
                      "Minimum font size for MRP declaration based on package area."),
    dict(rule_code="LM-010", severity="MEDIUM",
         title="Missing FSSAI License Number",
         description="Food Safety and Standards (Packaging and Labelling) Regulations, 2011 — "
                      "Regulation 2.1.1(3): Mandatory declaration of the FSSAI license number."),
    dict(rule_code="LM-011", severity="LOW",
         title="Missing Batch/Lot Number",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6, sub-rule (1)(d): "
                      "Mandatory declaration of a batch or lot number by which the packing can be traced."),
    dict(rule_code="LM-012", severity="MEDIUM",
         title="Declarations Not Sufficiently Legible",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 9: All declarations "
                      "required under these rules shall be legible, prominent, and in conspicuous contrast "
                      "to the background."),
    dict(rule_code="LM-013", severity="LOW",
         title="Declarations Not in Required Language",
         description="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 2(l) read with Rule 6: "
                      "Declarations must be made in Hindi or English, in addition to any other language."),
]


class Command(BaseCommand):
    help = "Seed/update the ComplianceRule table used by the compliance engine."

    def handle(self, *args, **options):
        created, updated = 0, 0
        for rule_kwargs in RULES:
            code = rule_kwargs.pop("rule_code")
            _, was_created = ComplianceRule.objects.update_or_create(
                rule_code=code,
                defaults={**rule_kwargs, "is_active": True},
            )
            created += was_created
            updated += not was_created
            rule_kwargs["rule_code"] = code  # restore for idempotent re-runs

        self.stdout.write(self.style.SUCCESS(
            f"Seeded compliance rules: {created} created, {updated} updated."
        ))
