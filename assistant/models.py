from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    """One turn of a chat with the shopping assistant.

    Conversations are keyed by session so guests can chat too; `user` is set
    when the customer is logged in.
    """

    class Role(models.TextChoices):
        USER = 'user', 'Customer'
        ASSISTANT = 'assistant', 'Assistant'

    session_key = models.CharField(max_length=40, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    # The customer's thumbs up (True) or down (False) on an assistant reply.
    helpful = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f'{self.role}: {self.content[:50]}'
