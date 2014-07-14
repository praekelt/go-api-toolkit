"""
Tests for go_api utility functions.
"""

from twisted.internet.defer import Deferred
from twisted.internet.task import Clock
from twisted.trial.unittest import TestCase

from go_api.utils import defer_async


class TestDeferAsync(TestCase):
    def test_returns_deferred(self):
        d = defer_async('foo', reactor=Clock())
        self.assertTrue(isinstance(d, Deferred))

    def test_fires_only_after_reactor_runs(self):
        clock = Clock()
        d = defer_async('foo', reactor=clock)
        self.assertEqual(d.called, False)
        clock.advance(0)
        self.assertEqual(d.called, True)
        self.assertEqual(d.result, 'foo')