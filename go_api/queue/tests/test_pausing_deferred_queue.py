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

    def setUp(self):
        self.size = 3
        self.backlog = 2
        self.q = PausingDeferredQueue(size=self.size, backlog=self.backlog)

    def test_empty_queue_underflow(self):
        """
        This test ensures that when the amount of deferred gets is exceeded,
        a QueueUnderflow error is raised.
        """
        for i in range(self.backlog):
            self.q.get()
        self.assertRaises(defer.QueueUnderflow, self.q.get)

    def test_backlog_queue(self):
        """
        This test ensures that if there is a backlog of gets for a queue, they
        are fulfilled when values are placed into the queue.
        """
        gotten = []
        # Create backlog
        for i in range(self.backlog):
            self.q.get().addCallback(gotten.append)
        # Fill queue to satisfy backlog
        for i in range(self.backlog):
            d = self.q.put(i)
            self.assertEqual(self.successResultOf(d), None)
            self.assertEqual(gotten, list(range(i + 1)))

    def test_fill_queue(self):
        """
        This test ensures that we can create a queue of size size. If we try
        to add another object to the queue, the returned defer will only fire
        if an object is removed from the queue.
        """
        for i in range(self.size - 1):
            d = self.q.put(i)
            self.assertEqual(self.successResultOf(d), None)

        # This next put fills the queue, so the deferred we return will only
        # get its result when the queue shrinks.
        put_d = self.q.put(self.size)
        self.assertNoResult(put_d)

        # When we pull something out of the queue, put_d fires and we're able
        # to put another thing into the queue.
        gotten = []
        self.q.get().addCallback(gotten.append)
        self.assertEqual(gotten, [0])
        self.assertEqual(self.successResultOf(put_d), None)

        put_d = self.q.put(self.size)
        self.assertNoResult(put_d)

    def test_queue_overflow(self):
        """
        This test ensures that if you try to add more elements than size, that
        a QueueOverflow error will be thrown.
        """
        for i in range(self.size):
            self.q.put(i)

        self.assertRaises(defer.QueueOverflow, self.q.put, None)

    def test_queue_no_limits(self):
        """
        This test makes sure that we can put and get objects from the queue
        when there are no limits supplied.
        """
        self.q = PausingDeferredQueue()
        gotten = []
        for i in range(self.size):
            self.q.get().addCallback(gotten.append)
        for i in range(self.size):
            d = self.q.put(i)
            self.assertEqual(self.successResultOf(d), None)
        self.assertEqual(gotten, list(range(self.size)))

    def test_zero_size_overflow(self):
        """
        This test ensures that a QueueOverflow error is raised when there is a
        put request on a queue of size 0
        """
        self.q = PausingDeferredQueue(size=0)
        self.assertRaises(defer.QueueOverflow, self.q.put, None)

    def test_zero_backlog_underflow(self):
        """
        This test ensures that a QueueUnderflow error is raised when there is a
        get request on a queue with a backlog of 0.
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
