from django.contrib import admin

from .models import FAQ, ErrorCode, Ticket, TicketAttachment, TicketMessage


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'category', 'position', 'is_published', 'updated_at')
    list_editable = ('position', 'is_published')
    list_filter = ('category', 'is_published')
    search_fields = ('question', 'answer', 'keywords')


@admin.register(ErrorCode)
class ErrorCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'area', 'http_status', 'ticket_category')
    list_filter = ('area',)
    search_fields = ('code', 'title', 'meaning')


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('code', 'subject', 'customer', 'category', 'status', 'priority', 'assigned_to',
                    'csat_rating', 'created_at')
    list_filter = ('status', 'category', 'priority', 'source', 'csat_rating')
    search_fields = ('code', 'subject', 'customer__username', 'customer__email')
    readonly_fields = ('code', 'first_response_at', 'resolved_at')
    inlines = [TicketMessageInline, TicketAttachmentInline]
