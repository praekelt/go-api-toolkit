from twisted.internet.defer import (
    QueueOverflow, QueueUnderflow, Deferred, succeed)


class PausingDeferredQueue(object):
    """
    An event driven queue.

    Objects may be added as usual to this queue.  When an attempt is
    made to retrieve an object when the queue is empty, a L{Deferred} is
    returned which will fire when an object becomes available.

    @ivar size: The maximum number of objects to allow into the queue
    at a time.  When an attempt to add a new object would exceed this
    limit, L{QueueOverflow} is raised synchronously.  C{None} for no limit.

    @ivar backlog: The maximum number of L{Deferred} gets to allow at
    one time.  When an attempt is made to get an object which would
    exceed this limit, L{QueueUnderflow} is raised synchronously.  C{None}
    for no limit.
    """

    def __init__(self, size=None, backlog=None):
        self.waiting = []
        self.pending = []
        self.size = size
        self.backlog = backlog
        self._pending_put = None

    def _cancelGet(self, d):
        """
        Remove a deferred d from our waiting list, as the deferred has been
        canceled.

        Note: We do not need to wrap this in a try/except to catch d not
        being in self.waiting because this canceller will not be called if
        d has fired. put() pops a deferred out of self.waiting and calls
        it, so the canceller will no longer be called.

        @param d: The deferred that has been canceled.
        """
        self.waiting.remove(d)

    def put(self, obj):
        """
        Add an object to this queue.

        @raise QueueOverflow: Too many objects are in this queue.
        """
        if self.waiting:
            self.waiting.pop(0).callback(obj)
            return succeed(None)
        elif self.size is None or len(self.pending) < self.size:
            self.pending.append(obj)
            if len(self.pending) == self.size:
                self._pending_put = Deferred()
                return self._pending_put
            # We still have space, so return an already-fired deferred.
            return succeed(None)
        else:
            raise QueueOverflow()

    def get(self):
        """
        Attempt to retrieve and remove an object from the queue.

        @return: a L{Deferred} which fires with the next object available in
        the queue.

        @raise QueueUnderflow: Too many (more than C{backlog})
        L{Deferred}s are already waiting for an object from this queue.
        """
        if self.pending:
            result = self.pending.pop(0)
            if self._pending_put is not None:
                self._pending_put.callback(None)
                self._pending_put = None
            return succeed(result)
        elif self.backlog is None or len(self.waiting) < self.backlog:
            d = Deferred(canceller=self._cancelGet)
            self.waiting.append(d)
            return d
        else:
            raise QueueUnderflow()
