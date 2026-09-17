from django.contrib import admin
from .models import PackagingProject, DesignSpecification, DesignChatMessage


@admin.register(PackagingProject)
class PackagingProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'category', 'pack_type', 'net_quantity', 'quantity_unit', 'mrp', 'updated_at')
    list_filter = ('category', 'pack_type', 'diet_type')
    search_fields = ('title', 'generic_product_name', 'brand_name', 'user__username')


@admin.register(DesignSpecification)
class DesignSpecificationAdmin(admin.ModelAdmin):
    list_display = ('project', 'pdp_area_sqcm', 'min_font_size_mm', 'min_numeral_size_mm', 'generated_at')


@admin.register(DesignChatMessage)
class DesignChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'project', 'user', 'role', 'content_preview', 'created_at')
    list_filter = ('role', 'created_at')

    def content_preview(self, obj):
        return obj.content[:50]

