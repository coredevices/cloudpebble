import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings, Client

from utils.redis_helper import redis_client


@override_settings(
    QEMU_URLS=['http://qemu-test:80/'],
    QEMU_PUBLIC_URL='http://qemu-test:80/',
    QEMU_LAUNCH_AUTH_HEADER='test-auth',
    QEMU_LAUNCH_TIMEOUT=5,
)
class TestEmulatorReboot(TestCase):
    """
    Tests for the reboot flow: disconnect the existing emulator, then
    launch a fresh one via the existing launch_emulator endpoint.
    The reboot is handled entirely on the frontend (SharedPebble.reboot
    calls disconnect(true) then getPebble(kind)), so no dedicated backend
    endpoint is needed. These tests verify that the existing launch
    endpoint still works correctly after a disconnect.
    """

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client = Client()
        self.client.login(username='testuser', password='password')

    @mock.patch('ide.api.qemu.requests.post')
    def test_launch_emulator_returns_instance_data(self, mock_post):
        mock_post.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                'uuid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'ws_port': 12345,
                'vnc_display': 1,
                'vnc_ws_port': 12346,
            },
            raise_for_status=lambda: None,
        )

        response = self.client.post('/ide/emulator/launch', {
            'platform': 'basalt',
            'token': 'test-token',
            'tz_offset': '0',
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('uuid', data)
        self.assertIn('host', data)
        self.assertIn('ping_url', data)
        self.assertIn('kill_url', data)

    def test_launch_requires_login(self):
        client = Client()
        response = client.post('/ide/emulator/launch', {'platform': 'basalt', 'token': 't', 'tz_offset': '0'})
        self.assertEqual(response.status_code, 302)

    def test_launch_requires_post(self):
        response = self.client.get('/ide/emulator/launch')
        self.assertEqual(response.status_code, 405)

    @mock.patch('ide.api.qemu.requests.post')
    def test_launch_caches_instance_in_redis(self, mock_post):
        mock_post.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                'uuid': 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
                'ws_port': 54321,
                'vnc_display': 2,
                'vnc_ws_port': 54322,
            },
            raise_for_status=lambda: None,
        )

        self.client.post('/ide/emulator/launch', {
            'platform': 'basalt',
            'token': 'test-token',
            'tz_offset': '0',
        })

        redis_key = 'qemu-user-%s-basalt' % self.user.id
        cached = redis_client.get(redis_key)
        self.assertIsNotNone(cached)
        data = json.loads(cached)
        self.assertEqual(data['uuid'], 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff')