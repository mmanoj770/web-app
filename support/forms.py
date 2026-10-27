from django import forms

from orders.models import Order

from .models import Ticket

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """An image field that accepts several files and returns them as a list."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': 'image/*'}))
        kwargs.setdefault('required', False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if len(files) > MAX_ATTACHMENTS:
            raise forms.ValidationError(f'You can attach up to {MAX_ATTACHMENTS} photos.')
        cleaned = [super(MultipleImageField, self).clean(f, initial) for f in files]
        for f in cleaned:
            if f.size > MAX_ATTACHMENT_BYTES:
                raise forms.ValidationError(f'{f.name} is larger than 5 MB.')
        return cleaned


class TicketForm(forms.ModelForm):
    attachments = MultipleImageField(label='Photos (optional)',
                                     help_text='Up to 5 photos, 5 MB each. Helpful for damaged or wrong items.')

    class Meta:
        model = Ticket
        fields = ('category', 'order', 'subject', 'description')
        labels = {'order': 'Which order is this about?', 'description': 'Tell us what happened'}
        widgets = {
            'category': forms.RadioSelect,
            'order': forms.RadioSelect,
            'subject': forms.TextInput(attrs={'placeholder': 'A short summary, e.g. "Screen arrived cracked"'}),
            'description': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Include any details that will help us '
                                                                             'sort this out quickly.'}),
        }

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        # Customers can only attach their own orders; offer the ten most recent.
        recent = list(Order.objects.filter(user=customer).values_list('pk', flat=True)[:10])
        self.fields['order'].queryset = (Order.objects.filter(pk__in=recent)
                                         .prefetch_related('items__product__images'))
        self.fields['order'].empty_label = None
        self.fields['subject'].required = False

    def clean(self):
        data = super().clean()
        category = data.get('category')
        if category in Ticket.ORDER_CATEGORIES and not data.get('order') and self.fields['order'].queryset:
            self.add_error('order', 'Please choose the order this is about.')
        if not data.get('subject') and category:
            subject = Ticket.Category(category).label
            if data.get('order'):
                subject += f' · {data["order"].number}'
            data['subject'] = subject
        return data


class ReplyForm(forms.Form):
    body = forms.CharField(label='Message', widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Write a reply…'}))
    attachments = MultipleImageField(label='Add photos')


class FeedbackForm(forms.ModelForm):
    csat_rating = forms.TypedChoiceField(choices=[(i, i) for i in range(1, 6)], coerce=int,
                                         widget=forms.RadioSelect, label='How did we do?')

    class Meta:
        model = Ticket
        fields = ('csat_rating', 'csat_comment')
        labels = {'csat_comment': 'Anything we could do better? (optional)'}
        widgets = {'csat_comment': forms.TextInput(attrs={'placeholder': 'Your feedback'})}
