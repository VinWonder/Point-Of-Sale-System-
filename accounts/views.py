from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404

from .audit import log_action
from .decorators import role_required
from .forms import StaffCreateForm, StaffEditForm, StaffPasswordForm
from .models import User


def _manageable(actor):
    """Staff the actor is allowed to manage."""
    if actor.role == User.Role.OWNER:
        return User.objects.all()
    return User.objects.filter(branch_id=actor.branch_id, role=User.Role.CASHIER)


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_list(request):
    staff = User.objects.select_related('branch').annotate(
        sales_count=Count('sale', filter=~Q(sale__status='VOIDED')),
    ).order_by('-is_active', 'branch__name', 'username')
    if request.user.role == User.Role.MANAGER:
        staff = staff.filter(branch_id=request.user.branch_id)
    manageable = set(_manageable(request.user).values_list('pk', flat=True))
    return render(request, 'accounts/staff_list.html', {'staff': staff, 'manageable': manageable})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_create(request):
    form = StaffCreateForm(request.POST or None, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        log_action(request.user, f'Created {user.get_role_display()} account {user.username}', user)
        messages.success(request, f'Staff member {user.username} created.')
        return redirect('accounts:staff_list')
    return render(request, 'accounts/staff_form.html', {'form': form, 'title': 'Add Staff'})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_edit(request, user_id):
    staff_member = get_object_or_404(_manageable(request.user), pk=user_id)
    form = StaffEditForm(request.POST or None, instance=staff_member, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_action(request.user, f'Updated staff {staff_member.username}', staff_member,
                   ', '.join(form.changed_data))
        messages.success(request, 'Staff member updated.')
        return redirect('accounts:staff_list')
    return render(request, 'accounts/staff_form.html', {
        'form': form, 'title': f'Edit {staff_member.username}', 'staff_member': staff_member,
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
def staff_set_password(request, user_id):
    staff_member = get_object_or_404(_manageable(request.user), pk=user_id)
    form = StaffPasswordForm(staff_member, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_action(request.user, f'Reset password for {staff_member.username}', staff_member)
        messages.success(request, f'New password set for {staff_member.username}.')
        return redirect('accounts:staff_list')
    return render(request, 'accounts/staff_form.html', {
        'form': form, 'title': f'Set password for {staff_member.username}',
    })


@login_required
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        log_action(user, 'Changed own password', user)
        messages.success(request, 'Your password has been changed.')
        return redirect('dashboard:index')
    return render(request, 'accounts/staff_form.html', {'form': form, 'title': 'Change my password'})


@role_required(User.Role.OWNER)
def audit_log(request):
    from core.utils import paginate
    from .models import AuditLog

    logs = AuditLog.objects.select_related('user')
    user_id = request.GET.get('user', '')
    if user_id.isdigit():
        logs = logs.filter(user_id=user_id)
    entity = request.GET.get('entity', '')
    if entity:
        logs = logs.filter(entity=entity)
    q = request.GET.get('q', '').strip()
    if q:
        logs = logs.filter(Q(action__icontains=q) | Q(details__icontains=q) | Q(entity_id=q))
    return render(request, 'accounts/audit_log.html', {
        'page_obj': paginate(request, logs, per_page=50),
        'users': User.objects.order_by('username'),
        'entities': AuditLog.objects.order_by().values_list('entity', flat=True).distinct(),
        'current_user': user_id, 'current_entity': entity, 'q': q,
    })
