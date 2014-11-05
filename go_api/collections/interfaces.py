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

    def stream(query):
        """
        Return a DeferredQueue of the objects in the collection. May return a
        deferred instead of the DeferredQueue. A queue item of False indicates
        the end of the queue.

        :param unicode query:
            Search term requested through the API. Defaults to ``None`` if no
            search term was requested.
        """

    def page(cursor, max_results, query):
        """
        Generages a page which contains a subset of the objects in the
        collection.

        :param unicode cursor:
            Used to determine the start point of the page. Defaults to ``None``
            if no cursor was supplied.
        :param int max_results:
            Used to limit the number of results presented in a page. Defaults
            to ``None`` if no limit was specified.
        :param unicode query:
            Search term requested through the API. Defaults to ``None`` if no
            search term was requested.

        :return:
            (cursor, data). ``cursor`` is an opaque string that refers to the
            next page, and is ``None`` if this is the last page. ``data`` is a
            list of all the objects within the page.
        :rtype: tuple
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
        Create an object within the collection and return the new ``object_id``
        and object data. May return a deferred.

        If ``object_id`` is ``None``, an identifier will be generated. Some
        collections may insist on generating their own ``object_id`` and raise
        a :class:`CollectionUsageError` if an ``object_id`` is given.

        Should raise :class:`CollectionObjectAlreadyExists` if ``object_id`` is
        not ``None`` and already exists.
        """

    def update(object_id, data):
        """
        Update an object and return the updated object data. May return a
        deferred.

        ``object_id`` may not be ``None``.

        Should raise :class:`CollectionObjectNotFound`` if ``object_id`` refers
        to an object that doesn't exist.
        """

    def delete(object_id):
        """
        Delete an object and return the deleted object data. May return a
        deferred.

        ``object_id`` may not be ``None``.

        Should raise :class:`CollectionObjectNotFound`` if ``object_id`` refers
        to an object that doesn't exist.
        """
