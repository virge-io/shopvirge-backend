from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.orm.exc import NoResultFound

from server.db import ShopTable, db, transactional
from server.db.database import Database, DBSessionMiddleware
from server.settings import app_settings
from server.utils.date_utils import nowtz
from tests.unit_tests.factories.shop import make_shop


def test_transactional():
    def insert_p(state):
        p = ShopTable(
            name="Test transactional",
            description="Testing 1, 2, 3!",
            modified_at=nowtz(),
        )
        db.session.add(p)

    def insert_p_error(state):
        p = ShopTable(
            name="Test transactional [ERROR]",
            description="Testing 1, 2, 3! BOOM!",
            modified_at=nowtz(),
        )
        db.session.add(p)
        raise Exception("Let's wreck some havoc!")

    logger = mock.MagicMock()

    with transactional(db, logger):
        insert_p({})
    logger.assert_has_calls(
        [
            mock.call.debug("Temporarily disabling commit."),
            mock.call.debug("Re-enabling commit."),
            mock.call.debug("Committing transaction."),
        ]
    )

    logger.reset_mock()
    with pytest.raises(Exception):  # noqa: B017 -- transactional() re-raises the body's error verbatim
        with transactional(db, logger):
            insert_p_error({})

    logger.assert_has_calls(
        [
            mock.call.debug("Temporarily disabling commit."),
            mock.call.debug("Re-enabling commit."),
            mock.call.warning("Rolling back transaction."),
        ]
    )


def test_transactional_no_commit():
    def insert_p(state):
        p = ShopTable(
            name="Test transactional should not be committed",
            description="Testing 1, 2, 3!",
            modified_at=nowtz(),
        )
        db.session.add(p)
        db.session.commit()

        raise Exception("Lets rollback")

    logger = mock.MagicMock()

    with pytest.raises(Exception, match="Lets rollback"):
        with transactional(db, logger):
            insert_p({})

    assert (
        db.session.query(ShopTable).filter(ShopTable.name == "Test transactional should not be committed").all() == []
    )
    logger.assert_has_calls(
        [
            mock.call.warning(
                "Tried to issue a commit. It should not! Transactional will execute commit when it returns."
            ),
        ]
    )


def test_transactional_no_commit_second_thread():
    def insert_p(state):
        p = ShopTable(
            name="Test transactional should not be committed",
            description="Testing 1, 2, 3!",
            modified_at=nowtz(),
        )
        db.session.add(p)
        db.session.commit()

        # Create new database session to simulate another api handler running at the same time
        # This is also a workaround for our disable commit wrapper, but it should be reasonable obvious that
        # someone is fucking around if you see `with db.database_scope():` in actual production code

        with db.database_scope():
            p2 = ShopTable(
                name="Test transactional should be committed",
                description="Testing 1, 2, 3!",
                modified_at=nowtz(),
            )
            db.session.add(p2)
            db.session.commit()

        raise Exception("Lets rollback")

    logger = mock.MagicMock()

    with pytest.raises(Exception, match="Lets rollback"):
        with transactional(db, logger):
            insert_p({})

    assert db.session.query(ShopTable).filter(ShopTable.name == "Test transactional should be committed").one()
    assert (
        db.session.query(ShopTable).filter(ShopTable.name == "Test transactional should not be committed").all() == []
    )
    logger.assert_has_calls(
        [
            mock.call.warning(
                "Tried to issue a commit. It should not! Transactional will execute commit when it returns."
            ),
        ]
    )


def test_autouse_fixture_rolls_back_aaa():
    # We want to test whether a change committed to the database in one test is visible to other tests (as in really
    # persisted to the database). Of course such a change should not be visible if our `fastapi_app` and `database`
    # autouse fixtures work as advertised.
    #
    # However, tests should be independent of each other and we cannot assume one test runs before the other. Hence
    # this test comes in two versions: one with the `_aaa` postfix and one with the `_bbb` postfix. Both will test
    # for the presence of a change the other test thinks it has committed to the database. If one of the tests (the
    # one that runs after the other) finds the change the other has committed our fixtures don't work properly.

    # Using Products as it's a simple model that doesn't require foreign keys.
    p = ShopTable(name="aaa", description="aaa", modified_at=nowtz())

    db.session.add(p)
    db.session.commit()

    with pytest.raises(NoResultFound):
        ShopTable.query.filter(ShopTable.name == "bbb").one()


def test_autouse_fixture_rolls_back_bbb():
    # We want to test whether a change committed to the database in one test is visible to other tests (as in really
    # persisted to the database). Of course such a change should not be visible if our `fastapi_app` and `database`
    # autouse fixtures work as advertised.
    #
    # However, tests should be independent of each other and we cannot assume one test runs before the other. Hence
    # this test comes in two versions: one with the `_aaa` postfix and one with the `_bbb` postfix. Both will test
    # for the presence of a change the other test thinks it has committed to the database. If one of the tests (the
    # one that runs after the other) finds the change the other has committed our fixtures don't work properly.

    # Using ResourceTypeTable as it's a simple model than doesn't require foreign keys.
    p = ShopTable(name="bbb", description="bbb", modified_at=nowtz())
    db.session.add(p)
    db.session.commit()

    with pytest.raises(NoResultFound):
        ShopTable.query.filter(ShopTable.name == "aaa").one()


# --- Returning the pooled connection early --------------------------------------------------------------------
#
# The 2026-10-19 incident exhausted the pool while Postgres sat idle: requests kept their connection through
# external calls and through the network send of the response. ``Database.release_connection`` and the
# middleware's release-at-response-start are the two mechanisms that stop that.


def _engine_bound_database() -> Database:
    """A ``Database`` on its own engine and pool, like production (the test session is bound to one connection)."""
    return Database(app_settings.DATABASE_URI)


def test_release_connection_returns_the_pooled_connection():
    database = _engine_bound_database()
    try:
        with database.database_scope():
            database.session.execute(text("SELECT 1"))
            assert database.engine.pool.checkedout() == 1
            database.release_connection()
            assert database.engine.pool.checkedout() == 0
            # The session stays usable: the next statement checks a connection out again.
            database.session.execute(text("SELECT 1"))
            assert database.engine.pool.checkedout() == 1
    finally:
        database.engine.dispose()


def test_release_connection_expires_loaded_objects_and_refuses_pending_changes():
    shop_id = make_shop(random_shop_name=True)
    shop = db.session.get(ShopTable, shop_id)

    db.release_connection()
    assert sa_inspect(shop).expired, "objects must be expired so later reads cannot serve stale data"
    assert shop.id == shop_id  # a later attribute access reloads transparently

    shop.description = "changed but not committed"
    with pytest.raises(RuntimeError, match="unflushed changes"):
        db.release_connection()
    db.session.expire(shop)  # discard the change again


def test_release_connection_refuses_flushed_but_uncommitted_changes():
    shop = ShopTable(name="flushed", description="flushed", modified_at=nowtz())  # keep a reference: the
    db.session.add(shop)  # transaction tracks flushed objects weakly
    db.session.flush()
    with pytest.raises(RuntimeError, match="flushed but uncommitted"):
        db.release_connection()
    db.session.expunge_all()


class _RecordCheckedOutAtResponseStart:
    """Outer ASGI wrapper: how many pool connections are still checked out when the response headers pass."""

    def __init__(self, app, pool) -> None:
        self.app = app
        self.pool = pool
        self.seen: list[int] = []

    async def __call__(self, scope, receive, send):
        async def spy(message):
            if message["type"] == "http.response.start":
                self.seen.append(self.pool.checkedout())
            await send(message)

        await self.app(scope, receive, spy)


def test_middleware_releases_the_connection_when_the_response_starts():
    database = _engine_bound_database()

    async def handler(scope, receive, send):
        database.session.execute(text("SELECT 1"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    recorder = _RecordCheckedOutAtResponseStart(DBSessionMiddleware(handler, database=database), database.engine.pool)
    try:
        client = TestClient(recorder)
        assert client.get("/shops/x/prices/").text == "ok"
        assert recorder.seen == [0], "the pooled connection must be back before the body is sent"
        # The MCP sub-app streams: its connection stays until the stream ends.
        assert client.get("/mcp/").text == "ok"
        assert recorder.seen == [0, 1]
        assert database.engine.pool.checkedout() == 0, "database_scope's finally still cleans up"
    finally:
        database.engine.dispose()
