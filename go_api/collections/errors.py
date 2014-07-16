"""
Exception classes for use in implementations of the ICollection interface.
"""


class CollectionError(Exception):
    """
    Base exception class for collection errors.
    """


class CollectionUsageError(Exception):
    """
    Raised by ICollections when they encounter invalid parameters or other
    errors that indicate that the caller has called a collection method
    incorrectly.
    """


class CollectionObjectNotFound(CollectionUsageError):
    """
    Raised by an ICollection when it is asked to get, update or delete an
    object that doesn't exist.
    """
    def __init__(self, object_id, object_type=u"Object"):
        CollectionUsageError.__init__(
            self, u"%s %r not found." % (object_type, object_id))


class CollectionObjectAlreadyExists(CollectionUsageError):
    """
    Raised by an ICollection when it is asked to get, update or delete an
    object that doesn't exist.
    """
    def __init__(self, object_id, object_type=u"Object"):
        CollectionUsageError.__init__(
            self, u"%s %r already exists." % (object_type, object_id))
