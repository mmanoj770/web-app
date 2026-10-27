from django.contrib import admin

from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'session_key', 'user', 'role', 'content')
    list_filter = ('role',)
    search_fields = ('content', 'user__username')
