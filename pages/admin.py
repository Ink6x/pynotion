from django.contrib import admin

from .models import Block, Page


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "parent", "position", "is_deleted", "updated_at")
    list_filter = ("is_deleted",)
    search_fields = ("title",)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("page", "type", "text", "position", "updated_at")
    list_filter = ("type",)
    search_fields = ("text",)
