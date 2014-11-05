from twisted.internet import defer
from twisted.trial import unittest

from go_api.queue import PausingDeferredQueue


class ImmediateFailureMixin(object):
    """
    Add additional assertion methods.
    """

    def assertImmediateFailure(self, deferred, exception):
        """
        Assert that the given Deferred current result is a Failure with the
        given exception.

        @return: The exception instance in the Deferred.
        """
        failures = []
        deferred.addErrback(failures.append)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].check(exception))
        return failures[0].value


class TestPausingDeferredQueue(
        unittest.SynchronousTestCase, ImmediateFailureMixin):

    def testQueue(self):
        N, M = 2, 2
        queue = defer.DeferredQueue(N, M)

        gotten = []

        for i in range(M):
            queue.get().addCallback(gotten.append)
        self.assertRaises(defer.QueueUnderflow, queue.get)

        for i in range(M):
            queue.put(i)
            self.assertEqual(gotten, list(range(i + 1)))
        for i in range(N):
            queue.put(N + i)
            self.assertEqual(gotten, list(range(M)))
        self.assertRaises(defer.QueueOverflow, queue.put, None)

        gotten = []
        for i in range(N):
            queue.get().addCallback(gotten.append)
            self.assertEqual(gotten, list(range(N, N + i + 1)))

        queue = defer.DeferredQueue()
        gotten = []
        for i in range(N):
            queue.get().addCallback(gotten.append)
        for i in range(N):
            queue.put(i)
        self.assertEqual(gotten, list(range(N)))

        queue = defer.DeferredQueue(size=0)
        self.assertRaises(defer.QueueOverflow, queue.put, None)

        queue = defer.DeferredQueue(backlog=0)
        self.assertRaises(defer.QueueUnderflow, queue.get)

    def test_PausingDeferredQueue(self):
        N, M = 3, 2
        queue = PausingDeferredQueue(N, M)

        gotten = []

        for i in range(M):
            queue.get().addCallback(gotten.append)
        self.assertRaises(defer.QueueUnderflow, queue.get)

        for i in range(M):
            d = queue.put(i)
            self.assertEqual(self.successResultOf(d), None)
            self.assertEqual(gotten, list(range(i + 1)))

        for i in range(N - 1):
            d = queue.put(M + i)
            self.assertEqual(self.successResultOf(d), None)
            self.assertEqual(gotten, list(range(M)))

        # This next put fills the queue, so the deferred we return will only
        # get its result when the queue shrinks.
        put_d = queue.put(N + M - 1)
        self.assertNoResult(put_d)

        # We already have a pending put, so we raise an exception.
        self.assertRaises(defer.QueueOverflow, queue.put, None)

        # When we pull something out of the queue, put_d fires and we're able
        # to put another thing into the queue.
        gotten = []
        queue.get().addCallback(gotten.append)
        self.assertEqual(gotten, [M])
        self.assertEqual(self.successResultOf(put_d), None)

        put_d = queue.put(N + M)
        self.assertNoResult(put_d)

        # Pull the remaining things out of the queue.
        for i in range(N):
            queue.get().addCallback(gotten.append)
            self.assertEqual(gotten, list(range(M, M + i + 2)))

        # Things are simpler when we have no limits.
        queue = PausingDeferredQueue()
        gotten = []
        for i in range(N):
            queue.get().addCallback(gotten.append)
        for i in range(N):
            d = queue.put(i)
            self.assertEqual(self.successResultOf(d), None)
        self.assertEqual(gotten, list(range(N)))

        queue = PausingDeferredQueue(size=0)
        self.assertRaises(defer.QueueOverflow, queue.put, None)

        queue = PausingDeferredQueue(backlog=0)
        self.assertRaises(defer.QueueUnderflow, queue.get)

    def test_cancelQueueAfterSynchronousGet(self):
        """
        When canceling a L{Deferred} from a L{PausingDeferredQueue} that already has
        a result, the cancel should have no effect.
        """
        def _failOnErrback(_):
            self.fail("Unexpected errback call!")

        queue = PausingDeferredQueue()
        d = queue.get()
        d.addErrback(_failOnErrback)
        queue.put(None)
        d.cancel()

    def test_cancelQueueAfterGet(self):
        """
        When canceling a L{Deferred} from a L{PausingDeferredQueue} that does not
        have a result (i.e., the L{Deferred} has not fired), the cancel
        causes a L{defer.CancelledError} failure. If the queue has a result
        later on, it doesn't try to fire the deferred.
        """
        queue = PausingDeferredQueue()
        d = queue.get()
        d.cancel()
        self.assertImmediateFailure(d, defer.CancelledError)

        def cb(ignore):
            # If the deferred is still linked with the deferred queue, it will
            # fail with an AlreadyCalledError
            queue.put(None)
            return queue.get().addCallback(self.assertIdentical, None)
        d.addCallback(cb)
        done = []
        d.addCallback(done.append)
        self.assertEqual(len(done), 1)
