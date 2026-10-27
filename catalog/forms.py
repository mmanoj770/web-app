from django import forms

from .models import Review


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(choices=[(i, i) for i in range(1, 6)], coerce=int, widget=forms.RadioSelect)

    class Meta:
        model = Review
        fields = ('rating', 'title', 'body')
        labels = {'body': 'Your review'}
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Sum it up in a few words'}),
            'body': forms.Textarea(attrs={'class': 'input', 'rows': 4, 'placeholder': 'What did you like or dislike?'}),
        }
