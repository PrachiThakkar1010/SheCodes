from django.contrib import admin
from .models import Complaint


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):

    list_display = (
        'complaint_id',
        'subject',
        'product_name',
        'company_name',
        'violation_category',
        'status',
        'submitted',
    )

    list_filter = (
        'status',
        'violation_category',
        'submitted',
    )

    search_fields = (
        'subject',
        'product_name',
        'company_name',
        'description',
    )

    ordering = (
        '-submitted',
    )

    readonly_fields = (
        'complaint_id',
        'submitted',
    )