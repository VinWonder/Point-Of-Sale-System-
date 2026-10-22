from django.test import Client, TestCase
from django.urls import reverse

from .models import User


class LoginFlowTests(TestCase):
    def test_owner_can_log_in_from_test_client(self):
        user = User.objects.create_superuser(
            username='owner',
            password='ChangeMe123!',
            role=User.Role.OWNER,
        )

        client = Client()
        response = client.post(
            reverse('login'),
            {'username': 'owner', 'password': 'ChangeMe123!'},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard:index'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertEqual(response.wsgi_request.user, user)


class StaffPermissionTests(TestCase):
    def setUp(self):
        from branches.models import Branch
        self.main = Branch.objects.create(name='Main')
        self.west = Branch.objects.create(name='West')
        self.owner = User.objects.create_user(username='boss', password='pw-123456!', role=User.Role.OWNER)
        self.manager = User.objects.create_user(username='mgr', password='pw-123456!',
                                                role=User.Role.MANAGER, branch=self.main)
        self.cashier = User.objects.create_user(username='cash', password='pw-123456!',
                                                role=User.Role.CASHIER, branch=self.main)
        self.other_cashier = User.objects.create_user(username='west', password='pw-123456!',
                                                      role=User.Role.CASHIER, branch=self.west)

    def create(self, actor, **data):
        self.client.force_login(actor)
        payload = {'username': 'new', 'password1': 'Strong-pass-981', 'password2': 'Strong-pass-981',
                   'role': 'CASHIER', 'branch': self.main.pk}
        payload.update(data)
        return self.client.post(reverse('accounts:staff_create'), payload)

    def test_manager_cannot_create_owner(self):
        self.create(self.manager, role='OWNER')
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_manager_cannot_create_staff_at_other_branch(self):
        self.create(self.manager, branch=self.west.pk)
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_manager_creates_cashier_at_own_branch(self):
        self.create(self.manager)
        self.assertEqual(User.objects.get(username='new').branch, self.main)

    def test_owner_can_create_manager(self):
        self.create(self.owner, role='MANAGER', branch=self.west.pk)
        self.assertEqual(User.objects.get(username='new').role, User.Role.MANAGER)

    def test_cashier_needs_branch(self):
        self.create(self.owner, branch='')
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_manager_cannot_edit_owner_or_other_branch(self):
        self.client.force_login(self.manager)
        for target in (self.owner, self.other_cashier, self.manager):
            with self.subTest(target=target.username):
                res = self.client.get(reverse('accounts:staff_edit', args=[target.pk]))
                self.assertEqual(res.status_code, 404)

    def test_cashier_cannot_open_staff_pages(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('accounts:staff_list')).status_code, 403)

    def test_owner_cannot_deactivate_self(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('accounts:staff_edit', args=[self.owner.pk]),
                         {'role': 'CASHIER', 'is_active': '', 'first_name': 'B'})
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertEqual(self.owner.role, User.Role.OWNER)

    def test_manager_resets_cashier_password(self):
        self.client.force_login(self.manager)
        self.client.post(reverse('accounts:staff_set_password', args=[self.cashier.pk]),
                         {'new_password1': 'Another-pass-552', 'new_password2': 'Another-pass-552'})
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password('Another-pass-552'))

    def test_login_is_audited(self):
        from .models import AuditLog
        self.client.post(reverse('login'), {'username': 'cash', 'password': 'pw-123456!'})
        self.client.post(reverse('login'), {'username': 'cash', 'password': 'wrong'})
        actions = list(AuditLog.objects.values_list('action', flat=True))
        self.assertIn('Logged in', actions)
        self.assertIn('Failed login attempt', actions)
