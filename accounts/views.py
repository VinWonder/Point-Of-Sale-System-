from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .decorators import role_required
from .forms import StaffCreateForm, StaffEditForm
from .models import User


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_list(request):
    staff = User.objects.all().order_by('username')
    return render(request, 'accounts/staff_list.html', {'staff': staff})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_create(request):
    if request.method == 'POST':
        form = StaffCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Staff member created.')
            return redirect('accounts:staff_list')
    else:
        form = StaffCreateForm()
    return render(request, 'accounts/staff_form.html', {'form': form, 'title': 'Add Staff'})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_edit(request, user_id):
    staff_member = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = StaffEditForm(request.POST, instance=staff_member)
        if form.is_valid():
            form.save()
            messages.success(request, 'Staff member updated.')
            return redirect('accounts:staff_list')
    else:
        form = StaffEditForm(instance=staff_member)
    return render(request, 'accounts/staff_form.html', {'form': form, 'title': 'Edit Staff'})
