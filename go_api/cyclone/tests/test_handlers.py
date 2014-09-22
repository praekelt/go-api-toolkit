import json

import treq
import yaml

from twisted.trial.unittest import TestCase
from twisted.python.failure import Failure
from twisted.internet.defer import inlineCallbacks, succeed, returnValue

from cyclone.web import HTTPError

from go_api.collections import InMemoryCollection
from go_api.collections.errors import CollectionUsageError
from go_api.cyclone.handlers import (
    BaseHandler, CollectionHandler, ElementHandler,
    join_paths, parse_route_vars, create_urlspec_regex, ApiApplication,
    owner_from_header, owner_from_path_kwarg, owner_from_oauth2_bouncer)
from go_api.cyclone.helpers import HandlerHelper, AppHelper, MockHttpServer


class DummyError(Exception):
    """
    Exception for use in tests.
    """


def raise_usage_error(*args, **kw):
    """
    Function that raises a generic :class:`CollectionUsageError`. For use in
    testing error paths.
    """
    raise CollectionUsageError("Do not push the red button")


def raise_dummy_error(*args, **kw):
    """
    Function that raises a :class:`DummyError`. For use in testing errors
    paths.
    """
    raise DummyError("You pushed the red button")


class TestJoinPaths(TestCase):
    def test_none(self):
        self.assertEqual(join_paths(""), "")

    def test_leading_slash(self):
        self.assertEqual(join_paths("/foo", "bar", "baz"), "/foo/bar/baz")

    def test_trailing_slash(self):
        self.assertEqual(join_paths("foo", "bar", "baz/"), "foo/bar/baz/")

    def test_leading_and_trailing_slash(self):
        self.assertEqual(join_paths("/foo", "bar", "baz/"), "/foo/bar/baz/")

    def test_no_slash(self):
        self.assertEqual(join_paths("foo"), "foo")

    def test_standalone_slash(self):
        self.assertEqual(join_paths("/"), "/")

    def test_empty_paths(self):
        self.assertEqual(
            join_paths("", "foo", "", "bar", "", "baz", ""),
            "foo/bar/baz")


class TestParseRouteVars(TestCase):
    def test_no_variables(self):
        self.assertEqual(parse_route_vars("/foo/bar"), [])

    def test_one_variable(self):
        self.assertEqual(parse_route_vars("/:foo/bar"), ["foo"])

    def test_two_variables(self):
        self.assertEqual(
            parse_route_vars("/:foo/bar/:baz"),
            ["foo", "baz"])


class TestCreateUrlspecRegex(TestCase):
    def test_no_variables(self):
        self.assertEqual(create_urlspec_regex("/foo/bar"), "/foo/bar")

    def test_one_variable(self):
        self.assertEqual(
            create_urlspec_regex("/:foo/bar"), "/(?P<foo>[^/]*)/bar")

    def test_two_variables(self):
        self.assertEqual(
            create_urlspec_regex("/:foo/bar/:baz"),
            "/(?P<foo>[^/]*)/bar/(?P<baz>[^/]*)")

    def test_trailing_slash(self):
        self.assertEqual(
            create_urlspec_regex("/foo/bar/"), "/foo/bar/")

    def test_no_slash(self):
        self.assertEqual(create_urlspec_regex("foo"), "foo")

    def test_standalone_slash(self):
        self.assertEqual(create_urlspec_regex("/"), "/")


class TestBaseHandler(TestCase):
    def setUp(self):
        self.handler_helper = HandlerHelper(
            BaseHandler, {"model_factory": lambda x: None})

    def assert_writes(self, writes, expected_objects):
        lines = "".join(writes).rstrip("\n").split("\n")
        received_objects = [json.loads(l) for l in lines]
        self.assertEqual(received_objects, expected_objects)

    def test_raise_err(self):
        handler = self.handler_helper.mk_handler()
        f = Failure(DummyError("Moop"))
        try:
            handler.raise_err(f, 500, "Eep")
        except HTTPError, err:
            pass
        self.assertEqual(err.status_code, 500)
        self.assertEqual(err.reason, "Eep")
        [err] = self.flushLoggedErrors(DummyError)
        self.assertEqual(err, f)

    def test_raise_err_reraises_httperrors(self):
        handler = self.handler_helper.mk_handler()
        f = Failure(HTTPError(300, reason="Sparta!"))
        try:
            handler.raise_err(f, 500, "Eep")
        except HTTPError, err:
            pass
        self.assertEqual(err.status_code, 300)
        self.assertEqual(err.reason, "Sparta!")
        self.assertEqual(self.flushLoggedErrors(HTTPError), [])

    def test_catch_err(self):
        handler = self.handler_helper.mk_handler()
        f = Failure(DummyError("Moop"))
        try:
            handler.catch_err(f, 400, DummyError)
        except HTTPError, err:
            pass
        self.assertEqual(err.status_code, 400)
        self.assertEqual(err.reason, "Moop")
        self.assertEqual(self.flushLoggedErrors(DummyError), [])

    def test_catch_err_reraises_other_errors(self):
        handler = self.handler_helper.mk_handler()
        f = Failure(DummyError("Moop"))
        try:
            handler.catch_err(f, 500, HTTPError)
        except DummyError, err:
            pass
        self.assertEqual(str(err), "Moop")
        self.assertEqual(self.flushLoggedErrors(DummyError), [])

    @inlineCallbacks
    def test_write_object(self):
        writes = []
        handler = self.handler_helper.mk_handler()
        handler.write = lambda d: writes.append(d)
        yield handler.write_object({"id": "foo"})
        self.assert_writes(writes, [
            {"id": "foo"},
        ])

    @inlineCallbacks
    def test_write_objects(self):
        writes = []
        handler = self.handler_helper.mk_handler()
        handler.write = lambda d: writes.append(d)
        yield handler.write_objects([
            {"id": "obj1"}, {"id": "obj2"},
        ])
        self.assert_writes(writes, [
            {"id": "obj1"},
            {"id": "obj2"},
        ])

    def test_mk_urlspec(self):
        class DummyHandler(BaseHandler):
            route_suffix = '/baz'

        model_factory = lambda x: None
        urlspec = DummyHandler.mk_urlspec('/bar/', model_factory, 'foo/')

        self.assertEqual(urlspec.handler_class, DummyHandler)
        self.assertEqual(urlspec.kwargs, {"model_factory": model_factory})
        self.assertEqual(urlspec.regex.pattern, 'foo/bar/baz$')

    def test_route_var_attrs(self):
        class DummyHandler(BaseHandler):
            route_suffix = '/:foo/:bar'

        self.handler_helper = HandlerHelper(
            DummyHandler, {"model_factory": lambda x: None})

    def test_initialize(self):
        model = {}
        helper = HandlerHelper(BaseHandler, {"model_factory": lambda x: model})
        handler = helper.mk_handler()
        self.assertEqual(handler.model_factory(handler), model)

    def test_prepare_model(self):
        model = {}
        helper = HandlerHelper(BaseHandler, {"model_factory": lambda x: model})
        handler = helper.mk_handler()
        handler.prepare()
        self.assertEqual(handler.model, model)

    def test_prepare_model_alias(self):
        class DummyHandler(BaseHandler):
            model_alias = "foo"

        model = {}
        helper = HandlerHelper(
            DummyHandler, {"model_factory": lambda x: model})

        handler = helper.mk_handler()
        handler.prepare()
        self.assertEqual(handler.foo, model)

    def test_prepare_no_model_alias(self):
        class DummyHandler(BaseHandler):
            model_alias = None

        helper = HandlerHelper(DummyHandler, {"model_factory": lambda x: None})
        handler = helper.mk_handler()

        # errors if BaseHandler doesn't know how to handle no model alias
        handler.prepare()

    def test_prepare_route_var_attrs(self):
        class DummyHandler(BaseHandler):
            route_suffix = '/:foo/:baz'

        helper = HandlerHelper(DummyHandler, {"model_factory": lambda x: None})
        handler = helper.mk_handler()
        handler.path_kwargs = {
            "foo": "bar",
            "baz": "quux"
        }
        handler.prepare()
        self.assertEqual(handler.foo, "bar")
        self.assertEqual(handler.baz, "quux")


class BaseHandlerTestCase(TestCase):
    @inlineCallbacks
    def check_error_response(self, resp, status_code, reason, **kw):
        self.assertEqual(resp.code, status_code)
        error_data = yield resp.json()
        expected = {
            "status_code": status_code,
            "reason": reason,
        }
        expected.update(kw)
        self.assertEqual(error_data, expected)


class TestCollectionHandler(BaseHandlerTestCase):
    def setUp(self):
        self.collection_data = {
            "obj1": {"id": "obj1"},
            "obj2": {"id": "obj2"},
        }
        self.collection = InMemoryCollection(self.collection_data)
        self.model_factory = lambda req: self.collection
        self.handler_helper = HandlerHelper(
            CollectionHandler,
            handler_kwargs={'model_factory': self.model_factory})
        self.app_helper = AppHelper(
            urlspec=CollectionHandler.mk_urlspec(
                '/root', self.model_factory))

    @inlineCallbacks
    def test_get_stream(self):
        data = yield self.app_helper.get('/root/?stream=true',
                                         parser='json_lines')
        self.assertEqual(data, [{"id": "obj1"}, {"id": "obj2"}])

    @inlineCallbacks
    def test_get_page(self):
        data = yield self.app_helper.get('/root/',
                                         parser='json')
        self.assertEqual(data, {
            u'cursor': None,
            u'data': [
                {u'id': u'obj1'},
                {u'id': u'obj2'},
            ],
        })

    @inlineCallbacks
    def test_get_page_bad_limit(self):
        data = yield self.app_helper.get('/root/?max_results=a')
        self.check_error_response(
            data,
            400,
            "max_results must be an integer")

    @inlineCallbacks
    def test_get_page_multiple(self):
        data = yield self.app_helper.get('/root/?max_results=1', parser='json')
        self.assertEqual(data[u'cursor'], 1)
        self.assertEqual(data[u'data'], [{u'id': u'obj1'}])

        data = yield self.app_helper.get('/root/?max_results=1&cursor=1',
                                         parser='json')
        self.assertEqual(data[u'cursor'], None)
        self.assertEqual(data[u'data'], [{u'id': u'obj2'}])

    @inlineCallbacks
    def test_get_usage_error(self):
        self.collection.page = raise_usage_error
        resp = yield self.app_helper.get('/root/')
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_get_server_error(self):
        self.collection.page = raise_dummy_error
        resp = yield self.app_helper.get('/root/')
        yield self.check_error_response(
            resp, 500, "Failed to retrieve objects.")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")

    @inlineCallbacks
    def test_post(self):
        data = yield self.app_helper.post(
            '/root/', data=json.dumps({"foo": "bar"}), parser='json')
        object_id = data["id"]
        self.assertEqual(data, {"foo": "bar", "id": object_id})
        self.assertEqual(
            self.collection_data[data["id"]],
            {"foo": "bar", "id": data["id"]})

    @inlineCallbacks
    def test_post_usage_error(self):
        self.collection.create = raise_usage_error
        resp = yield self.app_helper.post(
            '/root/', data=json.dumps({"foo": "bar"}))
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_post_server_error(self):
        self.collection.create = raise_dummy_error
        resp = yield self.app_helper.post(
            '/root/', data=json.dumps({"foo": "bar"}))
        yield self.check_error_response(
            resp, 500, "Failed to create object.")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")

    @inlineCallbacks
    def test_post_bad_json(self):
        """
        This test makes sure that if invalid json is received, the ValueError
        is correctly caught and returned as an HTTP 400 error.
        """
        data = yield self.app_helper.post('/root/', data='{', parser='json')
        self.assertEqual(data.get(u'status_code'), 400)
        self.assertEqual(data.get(u'reason').find('Invalid JSON: '), 0)


class TestElementHandler(BaseHandlerTestCase):
    def setUp(self):
        self.collection_data = {
            "obj1": {"id": "obj1"},
            "obj2": {"id": "obj2"},
        }
        self.collection = InMemoryCollection(self.collection_data)
        self.model_factory = lambda req: self.collection
        self.handler_helper = HandlerHelper(
            ElementHandler,
            handler_kwargs={'model_factory': self.model_factory})
        self.app_helper = AppHelper(
            urlspec=ElementHandler.mk_urlspec(
                '/root', self.model_factory))

    @inlineCallbacks
    def test_get(self):
        data = yield self.app_helper.get(
            '/root/obj1', parser='json')
        self.assertEqual(data, {"id": "obj1"})

    @inlineCallbacks
    def test_get_missing_object(self):
        resp = yield self.app_helper.get('/root/missing1')
        yield self.check_error_response(
            resp, 404, "Object 'missing1' not found.")

    @inlineCallbacks
    def test_get_usage_error(self):
        self.collection.get = raise_usage_error
        resp = yield self.app_helper.get('/root/obj1')
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_get_server_error(self):
        self.collection.get = raise_dummy_error
        resp = yield self.app_helper.get('/root/obj1')
        yield self.check_error_response(
            resp, 500, "Failed to retrieve 'obj1'")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")

    @inlineCallbacks
    def test_put(self):
        self.assertEqual(self.collection_data["obj2"], {"id": "obj2"})
        data = yield self.app_helper.put(
            '/root/obj2',
            data=json.dumps({"id": "obj2", "foo": "bar"}),
            parser='json')
        self.assertEqual(data, {"id": "obj2", "foo": "bar"})
        self.assertEqual(
            self.collection_data["obj2"],
            {"id": "obj2", "foo": "bar"})

    @inlineCallbacks
    def test_put_missing_object(self):
        resp = yield self.app_helper.put(
            '/root/missing1', data=json.dumps({"id": "missing1"}))
        yield self.check_error_response(
            resp, 404, "Object 'missing1' not found.")

    @inlineCallbacks
    def test_put_usage_error(self):
        self.collection.update = raise_usage_error
        resp = yield self.app_helper.put(
            '/root/obj1', data=json.dumps({"id": "obj2", "foo": "bar"}))
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_put_server_error(self):
        self.collection.update = raise_dummy_error
        resp = yield self.app_helper.put(
            '/root/obj2', data=json.dumps({"id": "obj2", "foo": "bar"}))
        yield self.check_error_response(
            resp, 500, "Failed to update 'obj2'")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")

    @inlineCallbacks
    def test_put_bad_json(self):
        """
        This test makes sure that if invalid json is received, the ValueError
        is correctly caught and returned as an HTTP 400 error.
        """
        self.assertEqual(self.collection_data["obj2"], {"id": "obj2"})
        data = yield self.app_helper.put(
            '/root/obj2',
            data='{',
            parser='json')
        self.assertEqual(data.get(u'status_code'), 400)
        self.assertEqual(data.get(u'reason').find('Invalid JSON: '), 0)

    @inlineCallbacks
    def test_delete(self):
        self.assertTrue("obj1" in self.collection_data)
        data = yield self.app_helper.delete(
            '/root/obj1', parser='json')
        self.assertEqual(data, {"id": "obj1"})
        self.assertTrue("obj1" not in self.collection_data)

    @inlineCallbacks
    def test_delete_missing_object(self):
        resp = yield self.app_helper.delete('/root/missing1')
        yield self.check_error_response(
            resp, 404, "Object 'missing1' not found.")

    @inlineCallbacks
    def test_delete_usage_error(self):
        self.collection.delete = raise_usage_error
        resp = yield self.app_helper.delete('/root/obj1')
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_delete_server_error(self):
        self.collection.delete = raise_dummy_error
        resp = yield self.app_helper.delete('/root/obj1')
        yield self.check_error_response(
            resp, 500, "Failed to delete 'obj1'")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")


class TestApiApplication(TestCase):
    def setUp(self):
        # these helpers should never have their collection factories
        # called in these tests
        self._cleanup_funcs = []
        self.collection_helper = HandlerHelper(
            CollectionHandler,
            handler_kwargs={
                "model_factory": self.uncallable_model_factory,
            })
        self.element_helper = HandlerHelper(
            ElementHandler,
            handler_kwargs={
                "model_factory": self.uncallable_model_factory,
            })

    @inlineCallbacks
    def tearDown(self):
        for func in reversed(self._cleanup_funcs):
            yield func()

    def add_cleanup(self, func):
        self._cleanup_funcs.append(func)

    @inlineCallbacks
    def start_fake_auth_server(self, owner_id):
        def auth_request(request):
            request.setHeader("X-Owner-Id", owner_id)
            return ""
        fake_server = MockHttpServer(auth_request)
        yield fake_server.start()
        self.add_cleanup(fake_server.stop)
        returnValue(fake_server)

    def get_collection_factory(self, data):
        collection = InMemoryCollection(data)
        return lambda _req: collection

    def get_app_helper(self, collections=ApiApplication.collections,
                       preprocessor=(
                           ApiApplication.factory_preprocessor),
                       config=None, extra_settings=None):
        class MyApiApplication(ApiApplication):
            pass

        MyApiApplication.collections = collections
        if callable(preprocessor):
            preprocessor = staticmethod(preprocessor)
        MyApiApplication.factory_preprocessor = preprocessor
        if extra_settings is None:
            extra_settings = {}
        return AppHelper(MyApiApplication(config, **extra_settings))

    @inlineCallbacks
    def test_process_request_health_check(self):
        app_helper = self.get_app_helper()
        result = yield app_helper.request('GET', '/health/')
        content = yield result.content()
        self.assertEqual(result.code, 200)
        self.assertEqual(content, "OK")

    @inlineCallbacks
    def test_process_request_default_preprocessor(self):
        collection_data = {'foo': {'id': 'foo'}}
        model_factory = self.get_collection_factory(collection_data)
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),))
        result = yield app_helper.request(
            'GET', '/foo/store/?stream=true',
            headers={"X-Owner-ID": "owner-1"})
        content = yield result.content()
        self.assertEqual(json.loads(content), collection_data['foo'])

    @inlineCallbacks
    def test_process_request_no_preprocessor(self):
        collection_data = {'foo': {'id': 'foo'}}
        model_factory = self.get_collection_factory(collection_data)
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=None)
        result = yield app_helper.request('GET', '/foo/store/?stream=true')
        content = yield result.content()
        self.assertEqual(json.loads(content), collection_data['foo'])

    @inlineCallbacks
    def test_process_request_async_preprocessor(self):
        collection_data = {'foo': {'id': 'foo'}}
        model_factory = self.get_collection_factory(collection_data)
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=lambda handler: succeed("owner-1"))
        result = yield app_helper.request('GET', '/foo/store/?stream=true')
        content = yield result.content()
        self.assertEqual(json.loads(content), collection_data['foo'])

    @inlineCallbacks
    def test_process_request_bouncer_preprocessor(self):
        collection_data = {'foo': {'id': 'foo'}}
        model_factory = self.get_collection_factory(collection_data)
        auth_server = yield self.start_fake_auth_server("owner-1")
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=owner_from_oauth2_bouncer(auth_server.url))
        result = yield app_helper.request('GET', '/foo/store/?stream=true')
        content = yield result.content()
        self.assertEqual(json.loads(content), collection_data['foo'])

    def uncallable_model_factory(self, *args, **kw):
        """
        A model_factory for use in tests that need one but should never
        call it.
        """
        raise Exception("This model_factory should never be called")

    def test_build_routes_no_preprocesor(self):
        model_factory = self.uncallable_model_factory
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=None)
        routes = app_helper.app.handlers[0][1]
        [_health_route, collection_route, elem_route] = routes
        self.assertEqual(collection_route.handler_class, CollectionHandler)
        self.assertEqual(collection_route.regex.pattern,
                         "/(?P<owner_id>[^/]*)/store/$")
        self.assertEqual(collection_route.kwargs, {
            "model_factory": model_factory,
        })
        self.assertEqual(elem_route.handler_class, ElementHandler)
        self.assertEqual(elem_route.regex.pattern,
                         "/(?P<owner_id>[^/]*)/store/(?P<elem_id>[^/]*)$")
        self.assertEqual(elem_route.kwargs, {
            "model_factory": model_factory,
        })

    @inlineCallbacks
    def assert_handlers_get_owner(self, app, collection_name, **handler_kw):
        [_health_route, collection_route, elem_route] = app.handlers[0][1]

        handler = self.collection_helper.mk_handler(**handler_kw)
        model_factory = collection_route.kwargs["model_factory"]
        owner = yield model_factory(handler)
        self.assertEqual(owner, collection_name)

        handler = self.element_helper.mk_handler(**handler_kw)
        model_factory = elem_route.kwargs["model_factory"]
        owner = yield model_factory(handler)
        self.assertEqual(owner, collection_name)

    @inlineCallbacks
    def test_build_routes_with_default_preprocessor(self):
        model_factory = lambda owner_id: "collection-%s" % owner_id
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),))

        yield self.assert_handlers_get_owner(
            app_helper.app, "collection-owner-1",
            headers={"X-Owner-ID": "owner-1"})

    @inlineCallbacks
    def test_build_routes_with_header_preprocessor(self):
        model_factory = lambda owner_id: "collection-%s" % owner_id
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=owner_from_header("X-Foo-ID"))

        yield self.assert_handlers_get_owner(
            app_helper.app, "collection-owner-1",
            headers={"X-Foo-ID": "owner-1"})

    @inlineCallbacks
    def test_build_routes_with_path_kwargs_preprocessor(self):
        model_factory = lambda owner_id: "collection-%s" % owner_id
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=owner_from_path_kwarg("owner_id"))

        yield self.assert_handlers_get_owner(
            app_helper.app, "collection-owner-1",
            path_kwargs={"owner_id": "owner-1"})

    @inlineCallbacks
    def test_build_routes_with_async_preprocessor(self):
        model_factory = lambda owner_id: "collection-%s" % owner_id
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=lambda handler: succeed("owner-1"))

        yield self.assert_handlers_get_owner(
            app_helper.app, "collection-owner-1")

    @inlineCallbacks
    def test_build_routes_with_bouncer_preprocessor(self):
        auth_server = yield self.start_fake_auth_server("owner-1")
        model_factory = lambda owner_id: "collection-%s" % owner_id
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            preprocessor=owner_from_oauth2_bouncer(auth_server.url))

        yield self.assert_handlers_get_owner(
            app_helper.app, "collection-owner-1",
            headers={"Authorization": "Bearer token"})

    def test_get_config_settings_None(self):
        app = ApiApplication()
        self.assertEqual(app.get_config_settings(), {})
        self.assertEqual(app.get_config_settings(None), {})

    def test_get_config_settings(self):
        config_dict = {'foo': 'bar', 'baz': [1, 2, 3]}

        # Trial cleans this up for us.
        tempfile = self.mktemp()
        with open(tempfile, 'wb') as fp:
            yaml.safe_dump(config_dict, fp)

        app = ApiApplication()
        self.assertEqual(app.get_config_settings(tempfile), config_dict)

    def test_initialize_without_config(self):
        class MyApiApplication(ApiApplication):
            def initialize(self, settings, config):
                self.config_for_test = config

        app = MyApiApplication()
        self.assertEqual(app.config_for_test, {})

    def test_initialize_with_config(self):
        config_dict = {'foo': 'bar', 'baz': [1, 2, 3]}

        # Trial cleans this up for us.
        tempfile = self.mktemp()
        with open(tempfile, 'wb') as fp:
            yaml.safe_dump(config_dict, fp)

        class MyApiApplication(ApiApplication):
            def initialize(self, settings, config):
                self.config_for_test = config

        app = MyApiApplication(tempfile)
        self.assertEqual(app.config_for_test, config_dict)

    def test_configure_auth_bouncer(self):
        config_dict = {'auth_bouncer_url': 'http://example.com/'}

        # Trial cleans this up for us.
        tempfile = self.mktemp()
        with open(tempfile, 'wb') as fp:
            yaml.safe_dump(config_dict, fp)

        # There's no easy way to test equality of closures, so we just assert
        # that we don't have the default preprocessor.
        app = ApiApplication(tempfile)
        self.assertNotEqual(
            app.factory_preprocessor,
            ApiApplication.factory_preprocessor)

        # With no config specified, we should have the default preprocessor.
        app = ApiApplication()
        self.assertEqual(
            app.factory_preprocessor,
            ApiApplication.factory_preprocessor)

    def test_configure_url_path_prefix(self):
        config_dict = {'url_path_prefix': '/foo/bar'}

        # Trial cleans this up for us.
        tempfile = self.mktemp()
        with open(tempfile, 'wb') as fp:
            yaml.safe_dump(config_dict, fp)

        model_factory = self.get_collection_factory({})
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            config=tempfile)

        [health, collection, element] = app_helper.app.handlers[0][1]
        # No prefix for the health URL path.
        self.assertEqual(health.regex.pattern, r'/health/$')
        # We should have the prefix on the front of our other URL paths.
        self.assertEqual(
            collection.regex.pattern,
            r'/foo/bar/(?P<owner_id>[^/]*)/store/$')
        self.assertEqual(
            element.regex.pattern,
            r'/foo/bar/(?P<owner_id>[^/]*)/store/(?P<elem_id>[^/]*)$')

    def test_no_url_path_prefix(self):
        model_factory = self.get_collection_factory({})
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),))

        [health, collection, element] = app_helper.app.handlers[0][1]

        self.assertEqual(health.regex.pattern, r'/health/$')
        self.assertEqual(
            collection.regex.pattern,
            r'/(?P<owner_id>[^/]*)/store/$')
        self.assertEqual(
            element.regex.pattern,
            r'/(?P<owner_id>[^/]*)/store/(?P<elem_id>[^/]*)$')

    @inlineCallbacks
    def test_handler_log_suppression(self):
        handler_logs = []
        model_factory = self.get_collection_factory({})
        app_helper = self.get_app_helper(
            collections=(('/:owner_id/store', model_factory),),
            extra_settings={'log_function': handler_logs.append})

        # The collection handler should use default logging behaviour.
        handler_logs[:] = []  # Clear logs.
        yield app_helper.get('/foo/store/')
        self.assertEqual(len(handler_logs), 1)

        # The health check handler should suppress logging.
        handler_logs[:] = []  # Clear logs.
        yield app_helper.get('/health/')
        self.assertEqual(len(handler_logs), 0)


class TestAuthHandlers(TestCase):
    def setUp(self):
        self._cleanup_funcs = []
        self.dummy_helper = HandlerHelper(
            CollectionHandler,
            handler_kwargs={
                "model_factory": self.uncallable_model_factory,
            })

    @inlineCallbacks
    def tearDown(self):
        for func in reversed(self._cleanup_funcs):
            yield func()

    def add_cleanup(self, func):
        self._cleanup_funcs.append(func)

    @inlineCallbacks
    def start_fake_auth_server(self, owner_id=None, code=200):
        def auth_request(request):
            if request.method != "GET":
                request.setResponseCode(405)
                return ""
            request.setResponseCode(code)
            if owner_id is not None:
                request.setHeader("X-Owner-Id", owner_id)
            return ""
        fake_server = MockHttpServer(auth_request)
        yield fake_server.start()
        self.add_cleanup(fake_server.stop)
        returnValue(fake_server)

    def uncallable_model_factory(self, *args, **kw):
        """
        A model_factory for use in tests that need one but should never
        call it.
        """
        raise Exception("This model_factory should never be called")

    @inlineCallbacks
    def test_fake_auth_server_rejects_post(self):
        """
        Test that the fake auth server rejects non-GET requests.

        This is important for :meth:`test_owner_from_bouncer_post` below which
        should fail if the bouncer preprocesser makes a non-POST request.
        """
        auth_server = yield self.start_fake_auth_server()
        # Accepts GET
        resp = yield treq.get(auth_server.url, persistent=False)
        self.assertEqual(resp.code, 200)
        # Rejects POST
        resp = yield treq.post(auth_server.url, persistent=False)
        self.assertEqual(resp.code, 405)

    def test_owner_from_header_with_value(self):
        preprocessor = owner_from_header("X-Owner-Id")
        handler = self.dummy_helper.mk_handler(
            headers={"X-Owner-Id": "owner-1"})
        owner_id = preprocessor(handler)
        self.assertEqual(owner_id, "owner-1")

    def test_owner_from_header_without_value(self):
        preprocessor = owner_from_header("X-Owner-Id")
        handler = self.dummy_helper.mk_handler()
        err = self.assertRaises(HTTPError, preprocessor, handler)
        self.assertEqual(err.status_code, 401)

    def test_owner_from_path_kwarg_with_value(self):
        preprocessor = owner_from_path_kwarg("owner_id")
        handler = self.dummy_helper.mk_handler(
            path_kwargs={"owner_id": "owner-1"})
        owner_id = preprocessor(handler)
        self.assertEqual(owner_id, "owner-1")

    def test_owner_from_path_kwarg_without_value(self):
        preprocessor = owner_from_path_kwarg("owner_id")
        handler = self.dummy_helper.mk_handler()
        err = self.assertRaises(HTTPError, preprocessor, handler)
        self.assertEqual(err.status_code, 401)

    @inlineCallbacks
    def test_owner_from_bouncer_with_value(self):
        auth_server = yield self.start_fake_auth_server("owner-1")
        preprocessor = owner_from_oauth2_bouncer(auth_server.url)
        handler = self.dummy_helper.mk_handler(
            headers={"Authorization": "Bearer foo"})
        owner_id = yield preprocessor(handler)
        self.assertEqual(owner_id, "owner-1")

    @inlineCallbacks
    def test_owner_from_bouncer_post(self):
        auth_server = yield self.start_fake_auth_server("owner-1")
        preprocessor = owner_from_oauth2_bouncer(auth_server.url)
        handler = self.dummy_helper.mk_handler(
            headers={"Authorization": "Bearer foo"})
        handler.request.method = "POST"
        owner_id = yield preprocessor(handler)
        self.assertEqual(owner_id, "owner-1")

    @inlineCallbacks
    def test_owner_from_bouncer_without_value(self):
        auth_server = yield self.start_fake_auth_server(code=401)
        preprocessor = owner_from_oauth2_bouncer(auth_server.url)
        handler = self.dummy_helper.mk_handler()
        err = yield self.assertFailure(preprocessor(handler), HTTPError)
        self.assertEqual(err.status_code, 401)

    @inlineCallbacks
    def test_owner_from_bouncer_with_invalid_value(self):
        auth_server = yield self.start_fake_auth_server(code=403)
        preprocessor = owner_from_oauth2_bouncer(auth_server.url)
        handler = self.dummy_helper.mk_handler(
            headers={"Authorization": "Bearer foo"})
        err = yield self.assertFailure(preprocessor(handler), HTTPError)
        self.assertEqual(err.status_code, 403)
