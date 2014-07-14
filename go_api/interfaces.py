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
        """

    def create(object_id, data):
        """
        Create an object within the collection. May return a deferred.

        If ``object_id`` is ``None``, an identifier will be generated.
        """

    def update(object_id, data):
        """
        Update an object. May return a deferred.

        ``object_id`` may not be ``None``.
        """

    def delete(object_id):
        """
        Delete an object. May return a deferred.
        """
