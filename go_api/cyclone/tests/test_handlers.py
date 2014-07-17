import json

import yaml

from twisted.trial.unittest import TestCase
from twisted.python.failure import Failure
from twisted.internet.defer import inlineCallbacks

from cyclone.web import HTTPError

from go_api.collections import InMemoryCollection
from go_api.collections.errors import CollectionUsageError
from go_api.cyclone.handlers import (
    BaseHandler, CollectionHandler, ElementHandler,
    create_urlspec_regex, ApiApplication,
    owner_from_header, owner_from_path_kwarg)
from go_api.cyclone.helpers import HandlerHelper, AppHelper


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
        self.handler_helper = HandlerHelper(BaseHandler)

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
        self.collection_factory = lambda req: self.collection
        self.handler_helper = HandlerHelper(
            CollectionHandler,
            handler_kwargs={'collection_factory': self.collection_factory})
        self.app_helper = AppHelper(
            urlspec=CollectionHandler.mk_urlspec(
                '/root', self.collection_factory))

    def test_mk_urlspec(self):
        urlspec = CollectionHandler.mk_urlspec(
            '/root', self.collection_factory)
        self.assertEqual(urlspec.handler_class, CollectionHandler)
        self.assertEqual(urlspec.kwargs, {
            "collection_factory": self.collection_factory,
        })
        self.assertEqual(urlspec.regex.pattern, '/root$')

    def test_initialize(self):
        handler = self.handler_helper.mk_handler()
        self.assertEqual(handler.collection_factory(handler), self.collection)

    def test_prepare(self):
        handler = self.handler_helper.mk_handler()
        handler.prepare()
        self.assertEqual(handler.collection, self.collection)

    @inlineCallbacks
    def test_get(self):
        data = yield self.app_helper.get('/root', parser='json_lines')
        self.assertEqual(data, [{"id": "obj1"}, {"id": "obj2"}])

    @inlineCallbacks
    def test_get_usage_error(self):
        self.collection.all = raise_usage_error
        resp = yield self.app_helper.get('/root')
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_get_server_error(self):
        self.collection.all = raise_dummy_error
        resp = yield self.app_helper.get('/root')
        yield self.check_error_response(
            resp, 500, "Failed to retrieve objects.")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")

    @inlineCallbacks
    def test_post(self):
        data = yield self.app_helper.post(
            '/root', data=json.dumps({"foo": "bar"}), parser='json')
        object_id = data["id"]
        self.assertEqual(data, {"foo": "bar", "id": object_id})
        self.assertEqual(
            self.collection_data[data["id"]],
            {"foo": "bar", "id": data["id"]})

    @inlineCallbacks
    def test_post_usage_error(self):
        self.collection.create = raise_usage_error
        resp = yield self.app_helper.post(
            '/root', data=json.dumps({"foo": "bar"}))
        yield self.check_error_response(
            resp, 400, "Do not push the red button")

    @inlineCallbacks
    def test_post_server_error(self):
        self.collection.create = raise_dummy_error
        resp = yield self.app_helper.post(
            '/root', data=json.dumps({"foo": "bar"}))
        yield self.check_error_response(
            resp, 500, "Failed to create object.")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")


class TestElementHandler(BaseHandlerTestCase):
    def setUp(self):
        self.collection_data = {
            "obj1": {"id": "obj1"},
            "obj2": {"id": "obj2"},
        }
        self.collection = InMemoryCollection(self.collection_data)
        self.collection_factory = lambda req: self.collection
        self.handler_helper = HandlerHelper(
            ElementHandler,
            handler_kwargs={'collection_factory': self.collection_factory})
        self.app_helper = AppHelper(
            urlspec=ElementHandler.mk_urlspec(
                '/root', self.collection_factory))

    def test_mk_urlspec(self):
        urlspec = ElementHandler.mk_urlspec(
            '/root', self.collection_factory)
        self.assertEqual(urlspec.handler_class, ElementHandler)
        self.assertEqual(urlspec.kwargs, {
            "collection_factory": self.collection_factory,
        })
        self.assertEqual(urlspec.regex.pattern, '/root/(?P<elem_id>[^/]*)$')

    def test_initialize(self):
        handler = self.handler_helper.mk_handler()
        self.assertEqual(handler.collection_factory(handler), self.collection)

    def test_prepare(self):
        handler = self.handler_helper.mk_handler()
        handler.path_kwargs = {"elem_id": "id-1"}
        handler.prepare()
        self.assertEqual(handler.collection, self.collection)
        self.assertEqual(handler.elem_id, "id-1")

    @inlineCallbacks
    def test_get(self):
        data = yield self.app_helper.get(
            '/root/obj1', parser='json')
        self.assertEqual(data, {"id": "obj1"})

    @inlineCallbacks
    def test_get_missing_object(self):
        resp = yield self.app_helper.get('/root/missing1')
        yield self.check_error_response(
            resp, 404, "Object u'missing1' not found.")

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
            resp, 500, "Failed to retrieve u'obj1'")
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
            resp, 404, "Object u'missing1' not found.")

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
            resp, 500, "Failed to update u'obj2'")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")

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
            resp, 404, "Object u'missing1' not found.")

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
            resp, 500, "Failed to delete u'obj1'")
        [f] = self.flushLoggedErrors(DummyError)
        self.assertEqual(str(f.value), "You pushed the red button")


class TestApiApplication(TestCase):
    def setUp(self):
        # these helpers should never have their collection factories
        # called in these tests
        self.collection_helper = HandlerHelper(
            CollectionHandler,
            handler_kwargs={
                "collection_factory": self.uncallable_collection_factory,
            })
        self.element_helper = HandlerHelper(
            ElementHandler,
            handler_kwargs={
                "collection_factory": self.uncallable_collection_factory,
            })

    def uncallable_collection_factory(self, *args, **kw):
        """
        A collection_factory for use in tests that need one but should never
        call it.
        """
        raise Exception("This collection_factory should never be called")

    def test_build_routes_no_preprocesor(self):
        collection_factory = self.uncallable_collection_factory
        app = ApiApplication()
        app.collections = (
            ('/:owner_id/store', collection_factory),
        )
        app.collection_factory_preprocessor = None
        [collection_route, elem_route] = app._build_routes()
        self.assertEqual(collection_route.handler_class, CollectionHandler)
        self.assertEqual(collection_route.regex.pattern,
                         "/(?P<owner_id>[^/]*)/store$")
        self.assertEqual(collection_route.kwargs, {
            "collection_factory": collection_factory,
        })
        self.assertEqual(elem_route.handler_class, ElementHandler)
        self.assertEqual(elem_route.regex.pattern,
                         "/(?P<owner_id>[^/]*)/store/(?P<elem_id>[^/]*)$")
        self.assertEqual(elem_route.kwargs, {
            "collection_factory": collection_factory,
        })

    def check_build_routes_with_preprocessor(self, preprocessor=None,
                                             **handler_kw):
        collection_factory = lambda owner_id: "collection-%s" % owner_id
        app = ApiApplication()
        app.collections = (
            ('/:owner_id/store', collection_factory),
        )
        if preprocessor is not None:
            app.collection_factory_preprocessor = preprocessor

        [collection_route, elem_route] = app._build_routes()

        handler = self.collection_helper.mk_handler(**handler_kw)
        self.assertEqual(
            collection_route.kwargs["collection_factory"](handler),
            "collection-owner-1")

        handler = self.element_helper.mk_handler(**handler_kw)
        self.assertEqual(
            elem_route.kwargs["collection_factory"](handler),
            "collection-owner-1")

    def test_build_routes_with_default_preprocessor(self):
        return self.check_build_routes_with_preprocessor(
            None,
            headers={"X-Owner-ID": "owner-1"})

    def test_build_routes_with_header_preprocessor(self):
        return self.check_build_routes_with_preprocessor(
            owner_from_header("X-Foo-ID"),
            headers={"X-Foo-ID": "owner-1"})

    def test_build_routes_with_path_kwargs_preprocessor(self):
        return self.check_build_routes_with_preprocessor(
            owner_from_path_kwarg("owner_id"),
            path_kwargs={"owner_id": "owner-1"})

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
