from zope.interface import Interface


class ICollection(Interface):
    """
    An interface to a collection of objects.
    """

    def all_keys():
        """
        Return an iterable over all keys in the collection. May return a
        deferred instead of the iterable.
        """

    def all():
        """
        Return an iterable over all objects in the collection. The iterable may
        contain deferreds instead of objects. May return a deferred instead of
        the iterable.
        """

    def get(object_id):
        """
        Return a single object from the collection. May return a deferred
        instead of the object.

        Should raise :class:`CollectionObjectNotFound`` if ``object_id`` refers
        to an object that doesn't exist.
        """

    def create(object_id, data):
        """
        Create an object within the collection. May return a deferred.

        If ``object_id`` is ``None``, an identifier will be generated. Some
        collections may insist on generating their own ``object_id`` and raise
        a :class:`CollectionUsageError` if an ``object_id`` is given.

        Should raise :class:`CollectionObjectAlreadyExists` if ``object_id`` is
        not ``None`` and already exists.
        """

    def update(object_id, data):
        """
        Update an object. May return a deferred.

        ``object_id`` may not be ``None``.

        Should raise :class:`CollectionObjectNotFound`` if ``object_id`` refers
        to an object that doesn't exist.
        """

    def delete(object_id):
        """
        Delete an object. May return a deferred.

        ``object_id`` may not be ``None``.

        Should raise :class:`CollectionObjectNotFound`` if ``object_id`` refers
        to an object that doesn't exist.
        """
