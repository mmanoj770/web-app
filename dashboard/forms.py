from django import forms
from django.contrib.auth import get_user_model

from catalog.models import Product
from orders.models import Order
from support.forms import MultipleImageField
from support.models import Ticket


class OrderStatusForm(forms.Form):
    status = forms.ChoiceField()
    carrier = forms.CharField(max_length=100, required=False)
    tracking_number = forms.CharField(max_length=100, required=False)
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = [
            (value, Order.Status(value).label) for value in order.allowed_transitions()
        ]

    def clean(self):
        data = super().clean()
        if data.get('status') == Order.Status.SHIPPED and not data.get('tracking_number'):
            self.add_error('tracking_number', 'A tracking number is required when shipping.')
        return data


class AgentReplyForm(forms.Form):
    body = forms.CharField(label='Message', widget=forms.Textarea(attrs={'rows': 4}))
    is_internal = forms.BooleanField(label='Internal note (hidden from customer)', required=False)
    attachments = MultipleImageField(label='Attach photos')


class TicketUpdateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ('status', 'priority', 'assigned_to')

    def __init__(self, *args, can_assign=True, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields['assigned_to'].queryset = User.objects.filter(
            role__in=[User.Role.AGENT, User.Role.ADMIN], is_active=True,
        )
        if not can_assign:
            del self.fields['assigned_to']


class ProductQuickEditForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('price', 'mrp', 'stock', 'is_active', 'is_featured')


class UserRoleForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('role', 'is_active')
