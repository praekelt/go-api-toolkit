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

    def test_empty_queue_underflow(self):
        """
        When the total amount of deferred gets is exceeded, a L{QueueUnderflow}
        error is raised.
        """
        backlog = 2
        q = PausingDeferredQueue(size=3, backlog=2)
        for i in range(backlog):
            q.get()
        self.assertRaises(defer.QueueUnderflow, q.get)

    def test_backlog_queue(self):
        """
        If there is a backlog of gets for a queue, they are fulfilled when
        values are placed into the queue.
        """
        backlog = 2
        q = PausingDeferredQueue(size=3, backlog=backlog)
        gotten = []
        # Create backlog
        for i in range(backlog):
            q.get().addCallback(gotten.append)
        # Fill queue to satisfy backlog
        for i in range(backlog):
            d = q.put(i)
            self.assertEqual(self.successResultOf(d), None)
            self.assertEqual(gotten, list(range(i + 1)))

    def test_fill_queue(self):
        """
        A queue of size size is created and filled. If we try to add another
        object to the queue, the returned defer will only fire if an object is
        removed from the queue.
        """
        size = 3
        q = PausingDeferredQueue(size=size, backlog=2)
        for i in range(size - 1):
            d = q.put(i)
            self.assertEqual(self.successResultOf(d), None)

        # This next put fills the queue, so the deferred we return will only
        # get its result when the queue shrinks.
        put_d = q.put(size)
        self.assertNoResult(put_d)

        # When we pull something out of the queue, put_d fires and we're able
        # to put another thing into the queue.
        gotten = []
        q.get().addCallback(gotten.append)
        self.assertEqual(gotten, [0])
        self.assertEqual(self.successResultOf(put_d), None)

        put_d = q.put(size)
        self.assertNoResult(put_d)

    def test_get_with_pending_put(self):
        """
        A put() call in a callback on a deferred returned from put() may be
        called synchronously before the get() that triggers it returns, so
        get() must handle this safely.
        """
        @defer.inlineCallbacks
        def fill_queue(q):
            for i in [0, 1, 2]:
                yield q.put(i)

        q = PausingDeferredQueue(size=1)
        fill_d = fill_queue(q)
        self.assertNoResult(fill_d)

        gotten = []
        q.get().addCallback(gotten.append)
        self.assertEqual(gotten, [0])
        self.assertNoResult(fill_d)

        q.get().addCallback(gotten.append)
        self.assertEqual(gotten, [0, 1])
        self.assertNoResult(fill_d)

        q.get().addCallback(gotten.append)
        self.assertEqual(gotten, [0, 1, 2])
        self.successResultOf(fill_d)

    def test_queue_overflow(self):
        """
        If you try to add more elements than size, a L{QueueOverflow} error
        will be thrown.
        """
        size = 3
        q = PausingDeferredQueue(size=size, backlog=2)
        for i in range(size):
            q.put(i)

        self.assertRaises(defer.QueueOverflow, q.put, None)

    def test_queue_no_limits(self):
        """
        You can put and get objects from the queue when there are no limits
        supplied.
        """
        q = PausingDeferredQueue()
        gotten = []
        for i in range(3):
            q.get().addCallback(gotten.append)
        for i in range(3):
            d = q.put(i)
            self.assertEqual(self.successResultOf(d), None)
        self.assertEqual(gotten, list(range(3)))

    def test_zero_size_overflow(self):
        """
        A L{QueueOverflow} error is raised when there is a put request on a
        queue of size 0
        """
        q = PausingDeferredQueue(size=0)
        self.assertRaises(defer.QueueOverflow, q.put, None)

    def test_zero_backlog_underflow(self):
        """
        A L{QueueUnderflow} error is raised when there is a get request on a
        queue with a backlog of 0.
        """
        queue = PausingDeferredQueue(backlog=0)
        self.assertRaises(defer.QueueUnderflow, queue.get)

    def test_cancelQueueAfterSynchronousGet(self):
        """
        When canceling a L{Deferred} from a L{PausingDeferredQueue} that
        already has a result, the cancel should have no effect.
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
        When canceling a L{Deferred} from a L{PausingDeferredQueue} that does
        not have a result (i.e., the L{Deferred} has not fired), the cancel
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
