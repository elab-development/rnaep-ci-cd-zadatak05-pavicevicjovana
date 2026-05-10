"""
Integration tests for the Payment service.
Tests interaction between application components and real infrastructure (Redis).
Requires a running Redis Stack instance (REDIS_HOST / REDIS_PORT env vars).
"""

import os
import pytest
import redis as redis_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def redis_conn():
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD") or None

    client = redis_client.Redis(
        host=host, port=port, password=password, decode_responses=True
    )
    try:
        client.ping()
    except redis_client.ConnectionError as exc:
        pytest.skip(f"Redis not reachable at {host}:{port} — {exc}")

    yield client
    client.close()


@pytest.fixture(scope="module")
def Order():
    """Import the Order model backed by the real Redis connection."""
    from main import Order as _Order
    return _Order


# ---------------------------------------------------------------------------
# Redis connectivity
# ---------------------------------------------------------------------------

class TestRedisConnectivity:

    def test_ping(self, redis_conn):
        assert redis_conn.ping() is True

    def test_set_and_get(self, redis_conn):
        redis_conn.set("test:ping_key", "ok", ex=10)
        assert redis_conn.get("test:ping_key") == "ok"

    def test_delete_key(self, redis_conn):
        redis_conn.set("test:delete_key", "value", ex=10)
        redis_conn.delete("test:delete_key")
        assert redis_conn.get("test:delete_key") is None


# ---------------------------------------------------------------------------
# Order model CRUD
# ---------------------------------------------------------------------------

class TestOrderModelCRUD:

    def test_save_and_retrieve_order(self, Order):
        order = Order(
            product_id="integ-prod-1",
            price=100.0,
            fee=20.0,
            total=240.0,
            quantity=2,
            status="pending",
        )
        order.save()

        retrieved = Order.get(order.pk)
        assert retrieved.product_id == "integ-prod-1"
        assert retrieved.price == pytest.approx(100.0)
        assert retrieved.fee == pytest.approx(20.0)
        assert retrieved.total == pytest.approx(240.0)
        assert retrieved.quantity == 2
        assert retrieved.status == "pending"

        Order.delete(order.pk)

    def test_update_order_status(self, Order):
        order = Order(
            product_id="integ-prod-2",
            price=50.0,
            fee=10.0,
            total=60.0,
            quantity=1,
            status="pending",
        )
        order.save()

        order.status = "completed"
        order.save()

        updated = Order.get(order.pk)
        assert updated.status == "completed"

        Order.delete(order.pk)

    def test_refund_order_status(self, Order):
        order = Order(
            product_id="integ-prod-3",
            price=75.0,
            fee=15.0,
            total=90.0,
            quantity=1,
            status="completed",
        )
        order.save()

        order.status = "refunded"
        order.save()

        refunded = Order.get(order.pk)
        assert refunded.status == "refunded"

        Order.delete(order.pk)

    def test_nonexistent_order_raises(self, Order):
        from redis_om import NotFoundError
        with pytest.raises(NotFoundError):
            Order.get("does-not-exist-pk-xyz")


# ---------------------------------------------------------------------------
# Redis Streams (used by process_order and consumer)
# ---------------------------------------------------------------------------

class TestRedisStreams:

    STREAM_KEY = "test:order_completed"

    def test_publish_to_stream(self, redis_conn):
        msg_id = redis_conn.xadd(
            self.STREAM_KEY,
            {"pk": "ord-1", "status": "completed", "product_id": "p-1"},
            "*",
        )
        assert msg_id is not None
        redis_conn.delete(self.STREAM_KEY)

    def test_read_from_stream(self, redis_conn):
        redis_conn.xadd(self.STREAM_KEY, {"pk": "ord-2", "status": "completed"}, "*")
        messages = redis_conn.xrange(self.STREAM_KEY, "-", "+")
        assert len(messages) >= 1
        redis_conn.delete(self.STREAM_KEY)

    def test_consumer_group_creation(self, redis_conn):
        stream = "test:refund_order"
        group = "test-payment-group"

        redis_conn.xadd(stream, {"data": "init"}, "*")

        try:
            redis_conn.xgroup_create(stream, group, "$", mkstream=True)
        except redis_client.ResponseError:
            pass  # group already exists

        groups = redis_conn.xinfo_groups(stream)
        group_names = [g["name"] for g in groups]
        assert group in group_names

        redis_conn.delete(stream)

    def test_model_dump_contains_required_fields(self, Order):
        """model_dump() output must include all fields needed for the stream message."""
        order = Order(
            product_id="integ-stream-prod",
            price=200.0,
            fee=40.0,
            total=480.0,
            quantity=2,
            status="completed",
        )
        order.save()

        data = order.model_dump()
        for field in ("pk", "product_id", "price", "fee", "total", "quantity", "status"):
            assert field in data

        Order.delete(order.pk)
