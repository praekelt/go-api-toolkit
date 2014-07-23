""" Base handlers for constructing APIs handlers from.
"""

import json
import traceback

import treq
import yaml

from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue
from twisted.python import log

from cyclone.web import RequestHandler, Application, URLSpec, HTTPError

from ..collections.errors import CollectionObjectNotFound, CollectionUsageError


def create_urlspec_regex(dfn, *args, **kw):
    """
    Create a URLSpec regex from a friendlier definition.

    Friendlier definitions look like:

      /foo/:var/baz/:other_var

    Generated regular expresions look like::

      /foo/(?P<var>[^/]*)/baz/(?P<other_var>[^/]*)
    """
    def replace_part(part):
        if not part.startswith(':'):
            return part
        name = part.lstrip(":")
        return "(?P<%s>[^/]*)" % (name,)

    parts = dfn.split("/")
    parts = [replace_part(p) for p in parts]
    return "/".join(parts)


class HealthHandler(RequestHandler):
    def get(self, *args, **kw):
        self.write("OK")


class BaseHandler(RequestHandler):
    """
    Base class for utility methods for :class:`CollectionHandler`
    and :class:`ElementHandler`.
    """

    def raise_err(self, failure, status_code, reason):
        """
        Catch any error, log the failure and raise a suitable
        :class:`HTTPError`.

        :type failure: twisted.python.failure.Failure
        :param failure:
            failure that caused the error.
        :param int status_code:
            HTTP status code to return.
        :param str reason:
            HTTP reason to return along with the status.
        """
        if failure.check(HTTPError):
            # re-raise any existing HTTPErrors
            failure.raiseException()
        log.err(failure)
        raise HTTPError(status_code, reason=reason)

    def catch_err(self, failure, status_code, expected_error):
        """
        Catch a specific error and re-raise it as a suitable
        :class:`HTTPError`. Do not log it.

        :type failure: twisted.python.failure.Failure
        :param failure:
            failure that caused the error.
        :type expected_error: subclass of :class:`Exception`
        :param expected_error:
            The exception class to trap.
        :param int status_code:
            HTTP status code to return.
        """
        if not failure.check(expected_error):
            failure.raiseException()
        raise HTTPError(status_code, reason=str(failure.value))

    def write_error(self, status_code, **kw):
        """
        Overrides :class:`RequestHandler`'s ``.write_error`` to format
        errors as JSON dictionaries.
        """
        error_data = {
            "status_code": status_code,
            "reason": str(kw.get("exception", self._reason)),
        }
        if self.settings.get("debug") and "exc_info" in kw:
            # in debug mode, try to send a traceback
            error_data["traceback"] = traceback.format_exception(
                *kw["exc_info"])
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.finish(json.dumps(error_data))

    def write_object(self, obj):
        """
        Write a serializable object out as JSON.

        :param dict obj:
            JSON serializable object to write out.
        """
        self.write(json.dumps(obj))

    @inlineCallbacks
    def write_objects(self, objs):
        """
        Write out a list of serialable objects as newline separated JSON.

        :param list objs:
            List of dictionaries to write out.
        """
        for obj_deferred in objs:
            obj = yield obj_deferred
            if obj is None:
                continue
            yield self.write_object(obj)
            self.write("\n")


# TODO: Sort out response metadata and make responses follow a consistent
#       pattern.

class CollectionHandler(BaseHandler):
    """
    Handler for operations on a collection as a whole.

    Methods supported:

    * ``GET /`` - return a list of items in the collection.
    * ``POST /`` - add an item to the collection.
    """

    @classmethod
    def mk_urlspec(cls, dfn, collection_factory):
        """
        Constructs a :class:`URLSpec` from a path definition and
        a collection factory. The returned :class:`URLSpec` routes
        the constructed path to a :class:`CollectionHandler` with the
        given ``collection_factory``.

        :param str dfn:
            A path definition suitbale for passing to
            :func:`create_urlspec_regex`. Any path arguments will
            appear in ``handler.path_kwargs`` on the ``handler`` passed
            to the ``collection_factory``.
        :param func collection_factory:
            A function that takes a :class:`RequestHandler` instance and
            returns an :class:`ICollection`. The collection_factory is
            called during ``RequestHandler.prepare``.
        """
        return URLSpec(create_urlspec_regex(dfn), cls,
                       kwargs={"collection_factory": collection_factory})

    def initialize(self, collection_factory):
        self.collection_factory = collection_factory

    @inlineCallbacks
    def prepare(self):
        self.collection = yield self.collection_factory(self)

    def get(self, *args, **kw):
        """
        Return all elements from a collection.
        """
        d = maybeDeferred(self.collection.all)
        d.addCallback(self.write_objects)
        d.addErrback(self.catch_err, 400, CollectionUsageError)
        d.addErrback(self.raise_err, 500, "Failed to retrieve objects.")
        return d

    def post(self, *args, **kw):
        """
        Create an element witin a collection.
        """
        data = json.loads(self.request.body)
        d = maybeDeferred(self.collection.create, None, data)
        # the result of .create is (object_id, obj)
        d.addCallback(lambda result: self.write_object(result[1]))
        d.addErrback(self.catch_err, 400, CollectionUsageError)
        d.addErrback(self.raise_err, 500, "Failed to create object.")
        return d


class ElementHandler(BaseHandler):
    """
    Handler for operations on an element within a collection.

    Methods supported:

    * ``GET /:elem_id`` - retrieve an element.
    * ``PUT /:elem_id`` - update an element.
    * ``DELETE /:elem_id`` - delete an element.
    """

    @classmethod
    def mk_urlspec(cls, dfn, collection_factory):
        """
        Constructs a :class:`URLSpec` from a path definition and
        a collection factory. The returned :class:`URLSpec` routes
        the constructed path, with an ``elem_id`` path suffix appended,
        to an :class:`ElementHandler` with the given ``collection_factory``.

        :param str dfn:
            A path definition suitbale for passing to
            :func:`create_urlspec_regex`. Any path arguments will
            appear in ``handler.path_kwargs`` on the ``handler`` passed
            to the ``collection_factory``.
        :param func collection_factory:
            A function that takes a :class:`RequestHandler` instance and
            returns an :class:`ICollection`. The collection_factory is
            called during ``RequestHandler.prepare``.
        """
        return URLSpec(create_urlspec_regex(dfn + '/:elem_id'), cls,
                       kwargs={"collection_factory": collection_factory})

    def initialize(self, collection_factory):
        self.collection_factory = collection_factory

    @inlineCallbacks
    def prepare(self):
        self.elem_id = self.path_kwargs['elem_id']
        self.collection = yield self.collection_factory(self)

    def get(self, *args, **kw):
        """
        Retrieve an element within a collection.
        """
        d = maybeDeferred(self.collection.get, self.elem_id)
        d.addCallback(self.write_object)
        d.addErrback(self.catch_err, 404, CollectionObjectNotFound)
        d.addErrback(self.catch_err, 400, CollectionUsageError)
        d.addErrback(self.raise_err, 500,
                     "Failed to retrieve %r" % (self.elem_id,))
        return d

    def put(self, *args, **kw):
        """
        Update an element within a collection.
        """
        data = json.loads(self.request.body)
        d = maybeDeferred(self.collection.update, self.elem_id, data)
        d.addCallback(self.write_object)
        d.addErrback(self.catch_err, 404, CollectionObjectNotFound)
        d.addErrback(self.catch_err, 400, CollectionUsageError)
        d.addErrback(self.raise_err, 500,
                     "Failed to update %r" % (self.elem_id,))
        return d

    def delete(self, *args, **kw):
        """
        Delete an element from within a collection.
        """
        d = maybeDeferred(self.collection.delete, self.elem_id)
        d.addCallback(self.write_object)
        d.addErrback(self.catch_err, 404, CollectionObjectNotFound)
        d.addErrback(self.catch_err, 400, CollectionUsageError)
        d.addErrback(self.raise_err, 500,
                     "Failed to delete %r" % (self.elem_id,))
        return d


def owner_from_header(header):
    """
    Return a function that retrieves a collection owner id from
    the specified HTTP header.

    :param str header:
       The name of the HTTP header. E.g. ``X-Owner-ID``.

    Typically used to build a collection factory that accepts
    an owner id instead of a :class:`RequestHandler`::
    """
    def owner_factory(handler):
        owner = handler.request.headers.get(header)
        if owner is None:
            raise HTTPError(401)
        return owner
    return owner_factory


def owner_from_path_kwarg(path_kwarg):
    """
    Return a function that retrieves a collection owner id from
    the specified path argument.

    :param str path_kwarg:
        The name of the path argument. E.g. ``owner_id``.
    """
    def owner_factory(handler):
        owner = handler.path_kwargs.get(path_kwarg)
        if owner is None:
            raise HTTPError(401)
        return owner
    return owner_factory


def owner_from_oauth2_bouncer(url_base):
    """
    Return a function that retrieves a collection owner id from a call to an
    auth service API.

    :param str url_base:
        The base URL to make an auth request to.

    """
    @inlineCallbacks
    def owner_factory(handler):
        request = handler.request
        uri = "".join([url_base.rstrip('/'), request.uri])
        resp = yield treq.request(
            request.method, uri, headers=request.headers, persistent=False)
        [owner] = resp.headers.getRawHeaders('X-Owner-Id')
        yield resp.content()
        if resp.code >= 400:
            raise HTTPError(resp.code)
        returnValue(owner)
    return owner_factory


def compose_deferred(f, g):
    """
    Compose two functions, ``f`` and ``g``, any of which may return a Deferred.
    """
    def h(*args, **kw):
        d = maybeDeferred(g, *args, **kw)
        d.addCallback(f)
        return d
    return h


def read_yaml_config(config_file, optional=True):
    """Parse an (usually) optional YAML config file."""
    if optional and config_file is None:
        return {}
    with file(config_file, 'r') as stream:
        # Assume we get a dict out of this.
        return yaml.safe_load(stream)


class ApiApplication(Application):
    """
    An API for a set of collections and adhoc additional methods.
    """

    config_required = False

    collections = ()

    collection_factory_preprocessor = staticmethod(
        owner_from_header('X-Owner-ID'))

    def __init__(self, config_file=None, **settings):
        if self.config_required and config_file is None:
            raise ValueError(
                "Please specify a config file using --appopts=<config.yaml>")
        config = self.get_config_settings(config_file)
        self.setup_collection_factory_preprocessor(config)
        self.initialize(settings, config)
        routes = self._build_routes()
        Application.__init__(self, routes, **settings)

    def initialize(self, settings, config):
        """
        Subclasses should override this to perform any application-level setup
        they need.
        """
        pass

    def setup_collection_factory_preprocessor(self, config):
        # TODO: Better configuration mechanism than this.
        auth_bouncer_url = config.get('auth_bouncer_url')
        if auth_bouncer_url is not None:
            self.collection_factory_preprocessor = (
                owner_from_oauth2_bouncer(auth_bouncer_url))

    def get_config_settings(self, config_file=None):
        return read_yaml_config(config_file)

    def _build_routes(self):
        """
        Build up routes for handlers from collections and
        extra routes.
        """
        routes = [URLSpec('/health/', HealthHandler)]
        for dfn, collection_factory in self.collections:
            if self.collection_factory_preprocessor is not None:
                collection_factory = compose_deferred(
                    collection_factory, self.collection_factory_preprocessor)
            routes.extend((
                CollectionHandler.mk_urlspec(dfn, collection_factory),
                ElementHandler.mk_urlspec(dfn, collection_factory),
            ))
        return routes
