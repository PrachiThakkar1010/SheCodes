from django.contrib import admin

from django.contrib import admin
from .models import ComplianceRule, ComplianceReport, ComplianceViolation

admin.site.register(ComplianceRule)
admin.site.register(ComplianceReport)
admin.site.register(ComplianceViolation)
