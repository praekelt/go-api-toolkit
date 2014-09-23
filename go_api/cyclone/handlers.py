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


class RouteParseError(Exception):
    "Raised when an erroneous route is parsed"


def join_paths(*paths):
    """
    Joins together the given paths with a '/'.

    .. code-block::

        join_paths("/foo/", "/bar/", "baz", "/quux/")
        # => /foo/bar/baz/quux/
    """
    # filter out empty strings
    paths = [p for p in paths if p]

    # simply return a single path or no paths (e.g. '/')
    if len(paths) < 2:
        return "".join(paths)

    # strip out leading and trailing slashes
    stripped = [p.strip("/") for p in paths]
    result = "/".join(p for p in stripped if p)

    # bring back the first leading slash if relevant
    if paths[0].startswith("/"):
        result = "/" + result

    # bring back the last trailing slash if relevant
    if paths[-1].endswith("/"):
        result = result + "/"

    return result


def duplicates(values):
    return set([v for v in values if values.count(v) > 1])


def parse_route_vars(dfn):
    return [p.lstrip(":") for p in dfn.split("/") if p.startswith(":")]


def create_urlspec_regex(dfn):
    """
    Create a URLSpec regex from a friendlier definition.

    Friendlier definitions look like:

      /foo/:var/baz/:other_var

    Generated regular expresions look like::

      /foo/(?P<var>[^/]*)/baz/(?P<other_var>[^/]*)
    """
    duplicate_vars = duplicates(parse_route_vars(dfn))

    if duplicate_vars:
        raise RouteParseError(
            "Duplicate route variables found: %s" %
            (",".join(duplicate_vars),))

    def replace_part(part):
        if not part.startswith(':'):
            return part
        name = part.lstrip(":")
        return "(?P<%s>[^/]*)" % (name,)

    parts = dfn.split("/")
    parts = [replace_part(p) for p in parts]
    return "/".join(parts)


class HealthHandler(RequestHandler):
    suppress_request_log = True

    def get(self, *args, **kw):
        self.write("OK")


class BaseHandler(RequestHandler):
    """
    Base class for utility methods for :class:`CollectionHandler`
    and :class:`ElementHandler`.
    """

    model_alias = None
    route_suffix = ""

    @classmethod
    def mk_urlspec(cls, dfn, model_factory, path_prefix=""):
        """
        Constructs a :class:`URLSpec` from a path definition and
        a model factory. The returned :class:`URLSpec` routes
        the constructed path to a :class:`BaseHandler` with the
        given ``model_factory``.

        :param str dfn:
            A path definition suitbale for passing to
            :func:`create_urlspec_regex`. Any path arguments will
            appear in ``handler.path_kwargs`` on the ``handler`` passed
            to the ``model_factory``.
        :param func model_factory:
            A function that takes a :class:`RequestHandler` instance and
            returns a model instance. The model_factory is
            called during ``RequestHandler.prepare``.
        :param str path_prefix:
            A prefix to add to the path ``dfn``. Defaults to ``""``.
        """
        dfn = join_paths(path_prefix, dfn, cls.route_suffix)

        return URLSpec(create_urlspec_regex(dfn), cls,
                       kwargs={"model_factory": model_factory})

    def initialize(self, model_factory):
        self.model_factory = model_factory

    @inlineCallbacks
    def prepare(self):
        for path_var in parse_route_vars(self.route_suffix):
            setattr(self, path_var, self.path_kwargs[path_var].encode('utf-8'))

        self.model = yield self.model_factory(self)

        if self.model_alias is not None:
            setattr(self, self.model_alias, self.model)

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
        Write out a list of serializable objects as newline separated JSON.

        :param list objs:
            List of dictionaries to write out.
        """
        for obj_deferred in objs:
            obj = yield obj_deferred
            if obj is None:
                continue
            yield self.write_object(obj)
            self.write("\n")

    def write_page(self, result):
        """
        Write out a list of serializable objects into one page with a pointer
        to the next page.

        :param unicode result[0]:
            Pointer to set to get the next page
        :param list result[1]:
            List of dictionaries to write out.
        """
        cursor, data = result
        page = {
            'cursor': cursor,
            'data': data,
        }
        self.write(json.dumps(page))

    def parse_json(self, data):
        try:
            return json.loads(data)
        except ValueError as e:
            raise HTTPError(400, reason="Invalid JSON: %s" % e)


# TODO: Sort out response metadata and make responses follow a consistent
#       pattern.

class CollectionHandler(BaseHandler):
    """
    Handler for operations on a collection as a whole.

    Methods supported:

    * ``GET /`` - return a list of items in the collection.
    * ``POST /`` - add an item to the collection.
    """

    route_suffix = "/"
    model_alias = "collection"

    def get(self, *args, **kw):
        """
        Return all elements from a collection.
        """
        query = self.get_argument('query', default=None)
        stream = self.get_argument('stream', default='false')
        if stream == 'true':
            d = maybeDeferred(self.collection.stream, query=query)
            d.addCallback(self.write_objects)
        else:
            cursor = self.get_argument('cursor', default=None)
            max_results = self.get_argument('max_results', default=None)
            try:
                max_results = max_results and int(max_results)
            except ValueError:
                raise HTTPError(400, "max_results must be an integer")
            d = maybeDeferred(
                self.collection.page, cursor=cursor,
                max_results=max_results, query=query)
            d.addCallback(self.write_page)

        d.addErrback(self.catch_err, 400, CollectionUsageError)
        d.addErrback(self.raise_err, 500, "Failed to retrieve objects.")
        return d

    def post(self, *args, **kw):
        """
        Create an element witin a collection.
        """
        data = self.parse_json(self.request.body)
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

    route_suffix = ":elem_id"
    model_alias = "collection"

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
        data = self.parse_json(self.request.body)
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
    Return a function that retrieves an owner id from the specified HTTP
    header.

    :param str header:
       The name of the HTTP header. E.g. ``X-Owner-ID``.

    Typically used to build a factory that accepts an owner id instead of a
    :class:`RequestHandler`::
    """
    def owner_factory(handler):
        owner = handler.request.headers.get(header)
        if owner is None:
            raise HTTPError(401)
        return owner
    return owner_factory


def owner_from_path_kwarg(path_kwarg):
    """
    Return a function that retrieves an owner id from the specified path
    argument.

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
    Return a function that retrieves an owner id from a call to an auth service
    API.

    :param str url_base:
        The base URL to make an auth request to.

    """
    @inlineCallbacks
    def owner_factory(handler):
        request = handler.request
        uri = "".join([url_base.rstrip('/'), request.uri])
        auth_headers = {}
        if 'Authorization' in request.headers:
            auth_headers['Authorization'] = request.headers['Authorization']
        resp = yield treq.get(uri, headers=auth_headers, persistent=False)
        yield resp.content()
        if resp.code >= 400:
            raise HTTPError(resp.code)
        [owner] = resp.headers.getRawHeaders('X-Owner-Id')
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

    models = ()
    collections = ()

    factory_preprocessor = staticmethod(owner_from_header('X-Owner-ID'))

    def __init__(self, config_file=None, **settings):
        if self.config_required and config_file is None:
            raise ValueError(
                "Please specify a config file using --appopts=<config.yaml>")
        config = self.get_config_settings(config_file)
        self.setup_factory_preprocessor(config)
        self.initialize(settings, config)
        path_prefix = self._get_configured_path_prefix(config)
        routes = self._build_routes(path_prefix)
        Application.__init__(self, routes, **settings)

    def initialize(self, settings, config):
        """
        Subclasses should override this to perform any application-level setup
        they need.
        """
        pass

    def setup_factory_preprocessor(self, config):
        # TODO: Better configuration mechanism than this.
        auth_bouncer_url = config.get('auth_bouncer_url')
        if auth_bouncer_url is not None:
            self.factory_preprocessor = (
                owner_from_oauth2_bouncer(auth_bouncer_url))

    def get_config_settings(self, config_file=None):
        return read_yaml_config(config_file)

    def _get_configured_path_prefix(self, config):
        prefix = config.get('url_path_prefix')
        return prefix or ""

    def _build_route(self, path_prefix, dfn, handler, factory):
        if self.factory_preprocessor is not None:
            factory = compose_deferred(factory, self.factory_preprocessor)

        return handler.mk_urlspec(dfn, factory, path_prefix=path_prefix)

    def _build_element_routes(self, path_prefix):
        """
        Build up routes for handlers.
        """
        return [
            self._build_route(path_prefix, dfn, ElementHandler, factory)
            for dfn, factory in self.collections]

    def _build_collection_routes(self, path_prefix):
        """
        Build up routes for handlers.
        """
        return [
            self._build_route(path_prefix, dfn, CollectionHandler, factory)
            for dfn, factory in self.collections]

    def _build_model_routes(self, path_prefix):
        """
        Build up routes for handlers.
        """
        return [
            self._build_route(path_prefix, dfn, handler, factory)
            for dfn, handler, factory in self.models]

    def _build_routes(self, path_prefix=""):
        """
        Build up routes for handlers from collections and
        extra routes.
        """
        routes = [URLSpec('/health/', HealthHandler)]
        routes.extend(self._build_collection_routes(path_prefix))
        routes.extend(self._build_element_routes(path_prefix))
        routes.extend(self._build_model_routes(path_prefix))
        return routes

    def log_request(self, handler):
        if getattr(handler, 'suppress_request_log', False):
            # The handler doesn't want to be logged, so we're done.
            return

        return Application.log_request(self, handler)
