"""
Tests for collection exception classes.
"""

from twisted.trial.unittest import TestCase

from go_api.collections.errors import (
    CollectionObjectNotFound, CollectionObjectAlreadyExists)


class TestCollectionObjectNotFound(TestCase):
    def test_str(self):
        e = CollectionObjectNotFound("object-1")
        self.assertEqual(str(e), "Object 'object-1' not found.")

    def test_str_custom_type(self):
        e = CollectionObjectNotFound("contact-1", "Contact")
        self.assertEqual(str(e), "Contact 'contact-1' not found.")


class TestCollectionObjectAlreadyExists(TestCase):
    def test_str(self):
        e = CollectionObjectAlreadyExists("object-1")
        self.assertEqual(str(e), "Object 'object-1' already exists.")

    def test_str_custom_type(self):
        e = CollectionObjectAlreadyExists("contact-1", "Contact")
        self.assertEqual(str(e), "Contact 'contact-1' already exists.")
