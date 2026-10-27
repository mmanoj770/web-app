from datetime import date

from django import forms

from .models import Order, Payment


class ShippingForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ('full_name', 'phone', 'address_line', 'city', 'postal_code')
        labels = {'address_line': 'Address (house no., street, area)', 'postal_code': 'PIN code'}
        widgets = {
            'phone': forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'tel'}),
            'postal_code': forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'postal-code'}),
        }

    def clean_postal_code(self):
        value = self.cleaned_data['postal_code'].strip()
        if not (value.isdigit() and len(value) == 6):
            raise forms.ValidationError('Enter a 6-digit PIN code.')
        return value


class PaymentForm(forms.Form):
    method = forms.ChoiceField(choices=Payment.Method.choices, initial=Payment.Method.UPI,
                               widget=forms.RadioSelect)
    upi_id = forms.CharField(label='UPI ID', max_length=100, required=False,
                             widget=forms.TextInput(attrs={'placeholder': 'yourname@okbank', 'autocomplete': 'off'}))
    card_number = forms.CharField(max_length=23, required=False, widget=forms.TextInput(attrs={
        'autocomplete': 'cc-number', 'inputmode': 'numeric', 'placeholder': '4242 4242 4242 4242',
    }))
    name_on_card = forms.CharField(max_length=100, required=False,
                                   widget=forms.TextInput(attrs={'autocomplete': 'cc-name'}))
    expiry = forms.CharField(max_length=5, required=False,
                             widget=forms.TextInput(attrs={'placeholder': 'MM/YY', 'autocomplete': 'cc-exp'}))
    cvc = forms.CharField(max_length=4, required=False, label='CVV',
                          widget=forms.PasswordInput(attrs={'autocomplete': 'cc-csc', 'inputmode': 'numeric'}))

    def clean(self):
        data = super().clean()
        if data.get('method') == Payment.Method.UPI:
            if not data.get('upi_id'):
                self.add_error('upi_id', 'Enter your UPI ID.')
            return data

        for field in ('card_number', 'name_on_card', 'expiry', 'cvc'):
            if not data.get(field):
                self.add_error(field, 'This field is required.')
        expiry = data.get('expiry') or ''
        try:
            month, year = (int(part) for part in expiry.split('/'))
            if not 1 <= month <= 12:
                raise ValueError
        except ValueError:
            if expiry:
                self.add_error('expiry', 'Use the format MM/YY.')
        else:
            today = date.today()
            if (2000 + year, month) < (today.year, today.month):
                self.add_error('expiry', 'This card has expired.')
        cvc = data.get('cvc') or ''
        if cvc and not (cvc.isdigit() and len(cvc) in (3, 4)):
            self.add_error('cvc', 'Enter the 3 or 4 digit code.')
        return data
