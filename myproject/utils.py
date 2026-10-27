from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def redirect_next(request, fallback, *args, **kwargs):
    """Redirect to ?next= / POST next if it points at this site, else to `fallback`."""
    target = request.POST.get('next') or request.GET.get('next')
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return redirect(target)
    return redirect(fallback, *args, **kwargs)


def wants_json(request):
    """True for fetch() calls from the site's JavaScript, which ask for JSON."""
    return 'application/json' in request.headers.get('Accept', '')
