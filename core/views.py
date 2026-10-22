from django.contrib import messages
from django.shortcuts import redirect, render

from accounts.audit import log_action
from accounts.decorators import role_required
from accounts.models import User
from .forms import ShopSettingsForm
from .models import ShopSettings


@role_required(User.Role.OWNER)
def shop_settings(request):
    settings = ShopSettings.load()
    form = ShopSettingsForm(request.POST or None, instance=settings)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_action(request.user, 'Updated shop settings', settings, ', '.join(form.changed_data))
        messages.success(request, 'Settings saved.')
        return redirect('core:settings')
    return render(request, 'core/settings.html', {'form': form})
