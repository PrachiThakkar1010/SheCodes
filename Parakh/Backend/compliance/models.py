from django.db import models

from django.db import models
from products.models import ProductScan

class ComplianceRule(models.Model):
    SEVERITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]

    rule_code = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='MEDIUM')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"[{self.rule_code}] {self.title}"


class ComplianceReport(models.Model):
    scan = models.OneToOneField(ProductScan, on_delete=models.CASCADE, related_name='compliance_report')
    is_compliant = models.BooleanField(default=False)
    overall_score = models.FloatField(default=0.0)
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "Passed" if self.is_compliant else "Failed"
        return f"Report #{self.id} for Scan #{self.scan.id} - {status}"


class ComplianceViolation(models.Model):
    report = models.ForeignKey(ComplianceReport, on_delete=models.CASCADE, related_name='violations')
    rule = models.ForeignKey(ComplianceRule, on_delete=models.CASCADE)
    details = models.TextField()

    def __str__(self):
        return f"Violation of {self.rule.rule_code} in Report #{self.report.id}"
