from django.db import models

from django.db import models
from django.contrib.auth.models import User

class ProductScan(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLIANT', 'Compliant'),
        ('NON_COMPLIANT', 'Non-Compliant'),
        ('NEEDS_MORE_IMAGES', 'Needs More Images'),
        ('FAILED', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scans', null=True, blank=True)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    image = models.ImageField(upload_to='product_scans/')
    scanned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    def __str__(self):
        username = self.user.username if self.user else "Guest"
        return f"{self.product_name or 'Unnamed Product'} - {self.user.username} ({self.scanned_at.strftime('%Y-%m-%d %H:%M')})"

    @property
    def image_count(self):
        return self.images.count()


class ProductScanImage(models.Model):
    """
    A single photo belonging to a scan. A scan needs several of these -
    front, back, side panels - to have any chance of covering every
    mandatory declaration; ProductScan.image (above) is kept as the first
    uploaded photo, purely so existing templates that already reference
    scan.image for a thumbnail (history.html, dashboard.html) keep working
    unchanged.
    """
    scan = models.ForeignKey(ProductScan, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='product_scans/')
    order = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Image {self.order} for Scan #{self.scan_id}"


class ExtractedLabelData(models.Model):
    scan = models.OneToOneField(ProductScan, on_delete=models.CASCADE, related_name='extracted_data')
    raw_ocr_text = models.TextField()

    # Every individual OCR line with its box/label/confidence, exactly
    # as labeler.py produced it, BEFORE aggregation into the structured
    # fields below - persisted so you can inspect what the labeler
    # actually did for a scan without re-running OCR (which is slow).
    # See products/views.py's result_json_view for how to view this.
    labeled_lines_json = models.JSONField(blank=True, null=True)

    # Structured declarations pulled out by the extraction engine
    # (compliance/engine/). Kept as plain text/JSON rather than typed
    # columns for the numeric ones, because OCR evidence is inherently
    # fuzzy - the rules engine re-validates format/value at check time.
    # product_name_declared/net_quantity_raw/mrp_raw/manufacturing_date_raw/
    # expiry_date_raw/batch_number/fssai_license_no are all TextField, not
    # a length-capped CharField - a real scan hit
    # "value too long for type character varying(50)" on fssai_license_no,
    # because these store RAW OCR text (which can be a messy multi-word
    # fragment, e.g. "tLICENSE NO. 10016026000857.US:PLOT NO. A"), not a
    # guaranteed-short clean value. The aggregator's fallback logic can
    # join multiple OCR lines together, so any of these could exceed a
    # short cap - same risk existed on all of them, not just the one that
    # happened to be hit first, so fixing them together.
    product_name_declared = models.TextField(blank=True, null=True)
    manufacturer_name = models.TextField(blank=True, null=True)
    manufacturer_address = models.TextField(blank=True, null=True)
    net_quantity_value = models.FloatField(blank=True, null=True)
    net_quantity_unit = models.CharField(max_length=10, blank=True, null=True)
    net_quantity_raw = models.TextField(blank=True, null=True)
    mrp_value = models.FloatField(blank=True, null=True)
    mrp_raw = models.TextField(blank=True, null=True)
    consumer_contact_raw = models.TextField(blank=True, null=True)

    ingredients = models.TextField(blank=True, null=True)
    nutritional_info = models.JSONField(blank=True, null=True)  # list of {nutrient, amount, unit, daily_value_pct}
    additives_info = models.JSONField(blank=True, null=True)  # list of {code, name, description, is_banned}

    manufacturing_date_raw = models.TextField(blank=True, null=True)
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date_raw = models.TextField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    batch_number = models.TextField(blank=True, null=True)
    fssai_license_no = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"OCR Data for Scan #{self.scan.id}"