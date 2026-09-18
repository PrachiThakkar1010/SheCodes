from django.contrib import admin
from .models import ProductScan, ExtractedLabelData


@admin.register(ProductScan)
class ProductScanAdmin(admin.ModelAdmin):
    if hasattr(ProductScan, 'created_at'):
        list_display = ('id', 'user', 'created_at')
    else:
        list_display = ('id', 'user')


admin.site.register(ExtractedLabelData)