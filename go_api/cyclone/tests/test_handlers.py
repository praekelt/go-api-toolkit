import json

from twisted.trial.unittest import TestCase
from twisted.python.failure import Failure
from twisted.internet.defer import inlineCallbacks

from cyclone.web import HTTPError

from go_api.collections import InMemoryCollection
from go_api.cyclone.handlers import (
    BaseHandler, CollectionHandler, ElementHandler,
    create_urlspec_regex, ApiApplication,
    owner_from_header, owner_from_path_kwarg)
from go_api.cyclone.helpers import HandlerHelper, AppHelper


class DummyError(Exception):
    """
    Exception for use in tests.
    """


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


class TestCollectionHandler(TestCase):
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
    def test_post(self):
        data = yield self.app_helper.post(
            '/root', data=json.dumps({"foo": "bar"}), parser='json')
        self.assertEqual(data.keys(), ["id"])
        self.assertEqual(
            self.collection_data[data["id"]],
            {"foo": "bar", "id": data["id"]})


class TestElementHandler(TestCase):
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
        self.assertEqual(resp.code, 404)
        error_data = yield resp.json()
        self.assertEqual(error_data, {
            "status_code": 404,
            "reason": "Object u'missing1' not found.",
        })

    @inlineCallbacks
    def test_put(self):
        self.assertEqual(self.collection_data["obj2"], {"id": "obj2"})
        data = yield self.app_helper.put(
            '/root/obj2',
            data=json.dumps({"id": "obj2", "foo": "bar"}),
            parser='json')
        self.assertEqual(data, {"success": True})
        self.assertEqual(
            self.collection_data["obj2"],
            {"id": "obj2", "foo": "bar"})

    @inlineCallbacks
    def test_put_missing_object(self):
        resp = yield self.app_helper.put(
            '/root/missing1',
            data=json.dumps({"id": "missing1"}))
        self.assertEqual(resp.code, 404)
        error_data = yield resp.json()
        self.assertEqual(error_data, {
            "status_code": 404,
            "reason": "Object u'missing1' not found.",
        })

    @inlineCallbacks
    def test_delete(self):
        self.assertTrue("obj1" in self.collection_data)
        data = yield self.app_helper.delete(
            '/root/obj1', parser='json')
        self.assertEqual(data, {"success": True})
        self.assertTrue("obj1" not in self.collection_data)

    @inlineCallbacks
    def test_delete_missing_object(self):
        resp = yield self.app_helper.delete('/root/missing1')
        self.assertEqual(resp.code, 404)
        error_data = yield resp.json()
        self.assertEqual(error_data, {
            "status_code": 404,
            "reason": "Object u'missing1' not found.",
        })


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
