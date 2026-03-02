from unittest.mock import patch

from django.db.utils import OperationalError
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from accounts.views import MyTokenObtainPairView


class MyTokenObtainPairViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_returns_503_when_database_not_ready(self):
        request = self.factory.post(
            '/api/token/',
            {'username': 'tester', 'password': 'secret'},
            format='json'
        )

        with patch(
            'accounts.views.BaseTokenObtainPairView.post',
            side_effect=OperationalError('database is not ready')
        ):
            response = MyTokenObtainPairView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['detail'], '认证服务正在启动，请稍后重试。')
