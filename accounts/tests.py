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
