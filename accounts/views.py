from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from myproject.utils import redirect_next

from .forms import ProfileForm, SignUpForm


def register(request):
    if request.user.is_authenticated:
        return redirect('catalog:home')
    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f'Welcome, {user.first_name}! Your account is ready.')
        return redirect_next(request, 'catalog:home')
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile updated.')
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {'form': form})
