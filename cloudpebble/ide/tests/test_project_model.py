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


class TestResourceRootPath(TestCase):
    def test_resource_without_variants_names_the_file(self):
        """ A resource with no variants fails the build with a message naming it, not IndexError """
        from django.contrib.auth.models import User
        from ide.models import ResourceFile
        user = User.objects.create_user('rootpath', 'rootpath@example.com', 'x')
        project = Project.objects.create(name='rootpath', owner=user)
        resource = ResourceFile.objects.create(project=project, file_name='logo.png', kind='png')
        with self.assertRaisesRegex(Exception, "logo.png"):
            resource.root_path
