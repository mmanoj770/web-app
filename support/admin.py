from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketMessage


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
