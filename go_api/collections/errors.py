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
