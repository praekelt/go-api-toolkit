"""
Helpers for use in tests.
"""

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet import reactor

import treq

from cyclone.web import Application


class _DummyConnection(object):
    """
    Extremely dummy connection for use with :class:`_DummyRequest`.
    """


class _DummyRequest(object):
    """
    Extremely dummy request for use with :meth:`HandlerHelper.mk_handler`.
    """
    def __init__(self):
        self.supports_http_1_1 = lambda: True
        self.connection = _DummyConnection()


class HandlerHelper(object):
    """
    Helper for performing very simple tests on cyclone handlers.

    :type handler_cls: A sub-class of :class:`cyclone.web.RequestHandler`.
    :param handler_cls:
        The handler class to help test.
    :param dict handler_kwargs:
        A dictionary of keyword arguments to pass to the handler's
        constructor.
    """
    def __init__(self, handler_cls, handler_kwargs=None):
        self.handler_cls = handler_cls
        self.handler_kwargs = handler_kwargs or {}

    def mk_handler(self):
        """
        Return a handler attached to a very stubby request object.

        Suitable for testing handler functionality that doesn't touch the
        request object itself.
        """
        request = _DummyRequest()
        app = Application([])
        return self.handler_cls(
            app, request, **self.handler_kwargs)


class AppHelper(object):
    """
    Helper for testing cyclone requests.

    :type app: :class:`cyclone.web.Application`
    :param app:
        The application to test. One may instead
        pass a ``urlspec`` parameter.
    :type urlspec: :class:`cyclone.web.URLSpec`
    :param urlspec:
        Test an app with just the one route specified
        by this :class:`cyclone.web.URLSpec`.
    """
    def __init__(self, app=None, urlspec=None, reactor=reactor):
        if app is None and urlspec is not None:
            app = Application([urlspec])
        if app is None:
            raise ValueError("Please specify one of app or urlspec")
        self.app = app
        self.reactor = reactor

    def _parse_bytes(self, response):
        return treq.content(response)

    def _parse_json(self, response):
        return treq.json_content(response)

    def _parse_json_lines(self, response):
        d = treq.content(response)
        d.addCallback(lambda s: [json.loads(l) for l in s.splitlines()])
        return d

    @inlineCallbacks
    def request(self, method, url_suffix, parser=None, **kw):
        """
        Start the application, make an HTTP request and then shutdown
        the application.

        :param str url_suffix:
            A path to make the request to.
        :param str parser:
            Response parser to use. Valid values are ``'bytes'``, ``'json'``,
            ``'json_lines'`` or ``None``. ``None`` indicates that the raw
            response object should be returned. Otherwise the parsed data is
            returned.

        Other parameters are the same as for :func:`treq.request`.
        """
        server = self.reactor.listenTCP(0, self.app, interface="127.0.0.1")
        host = server.getHost()
        # prefix the URL with the test server host and port
        url = ('http://127.0.0.1:%d' % host.port) + url_suffix
        # close the HTTP connection straight away so that the test
        # reactor is clean when we leave this function
        kw['persistent'] = False
        response = yield treq.request(method, url, reactor=self.reactor, **kw)
        if parser is not None:
            parser_method = getattr(self, '_parse_' + parser)
            response = yield parser_method(response)
        yield server.stopListening()
        server.loseConnection()
        returnValue(response)

    def get(self, url, **kw):
        return self.request('GET', url, **kw)

    def post(self, url, **kw):
        return self.request('POST', url, **kw)

    def put(self, url, **kw):
        return self.request('PUT', url, **kw)

    def delete(self, url, **kw):
        return self.request('DELETE', url, **kw)
