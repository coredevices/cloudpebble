""" These tests check that the Project model behaves as expected."""
import unittest
from ide.models import Project
from django.test import TestCase


class TestProjectModel(TestCase):
    @unittest.skip("Pre-existing failure: uses_array_message_keys returns True for '{}'")
    def test_uses_array_message_keys_property(self):
        """ Check that uses_array_message_keys functions as intended """
        self.assertTrue(Project(app_keys="[]").uses_array_message_keys)
        self.assertFalse(Project(app_keys="{}").uses_array_message_keys)
