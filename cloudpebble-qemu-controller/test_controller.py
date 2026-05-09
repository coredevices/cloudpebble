import json
import os
import unittest
from unittest import mock
from uuid import UUID

from flask import Flask

os.environ.setdefault('QEMU_IMAGE_ROOT', '/tmp/fake-images')

import settings
settings.QEMU_IMAGE_ROOT = '/tmp/fake-images'
settings.QEMU_BIN = 'echo'
settings.QEMU_DATA_DIR = None
settings.LAUNCH_AUTH_HEADER = 'test-auth'
settings.EMULATOR_LIMIT = 10
settings.PORT = 5001
settings.SSL_ROOT = None
settings.RUN_AS_USER = None
settings.DEBUG = True
settings.BLOCK_PRIVATE_ADDRESSES = False

from controller import app, emulators


class TestKillEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        emulators.clear()

    def tearDown(self):
        emulators.clear()

    def test_kill_removes_emulator(self):
        from emulator import Emulator
        emu_uuid = UUID('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        emu = mock.MagicMock(spec=Emulator)
        emulators[emu_uuid] = emu

        response = self.client.post('/qemu/%s/kill' % emu_uuid)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(emu_uuid, emulators)
        emu.kill.assert_called_once()

    def test_kill_404_for_unknown_uuid(self):
        response = self.client.post('/qemu/00000000-0000-0000-0000-000000000000/kill')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'ok')


class TestLaunchEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        emulators.clear()

    def tearDown(self):
        emulators.clear()

    def test_launch_requires_auth(self):
        response = self.client.post('/qemu/launch', data={
            'token': 'test', 'platform': 'basalt', 'version': '3.0'
        })
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()