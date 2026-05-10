"""
Functional tests for the Payment service API.
Treats the payment service as a black box — exercises real endpoints via TestClient.
The external Inventory service HTTP call is mocked; Redis is real.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from main import app
    # patch asyncio.sleep so the background task completes instantly in tests
    with patch("main.asyncio.sleep", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def inventory_product():
    return {"pk": "prod-func-1", "name": "Test Widget", "price": 100.0, "quantity": 50}


def _mock_inventory(product: dict):
    """Return a context manager that patches httpx to return the given product."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = product

    mock_async_client = AsyncMock()
    mock_async_client.get.return_value = mock_response

    mock_class = MagicMock()
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=False)

    return patch("main.httpx.AsyncClient", mock_class)


def _mock_inventory_not_found():
    """Return a context manager that patches httpx to simulate a missing product."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_async_client = AsyncMock()
    mock_async_client.get.return_value = mock_response

    mock_class = MagicMock()
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=False)

    return patch("main.httpx.AsyncClient", mock_class)


# ---------------------------------------------------------------------------
# GET /orders/{pk}
# ---------------------------------------------------------------------------

class TestGetOrder:

    def test_get_nonexistent_order_returns_404(self, client):
        response = client.get("/orders/nonexistent-pk-xyz")
        assert response.status_code == 404

    def test_get_nonexistent_order_has_detail_field(self, client):
        response = client.get("/orders/missing-order-000")
        body = response.json()
        assert "detail" in body

    def test_get_existing_order_returns_200(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            create_resp = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 1}
            )
        assert create_resp.status_code == 200
        pk = create_resp.json()["pk"]

        get_resp = client.get(f"/orders/{pk}")
        assert get_resp.status_code == 200

    def test_get_existing_order_returns_correct_pk(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            create_resp = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 1}
            )
        pk = create_resp.json()["pk"]

        get_resp = client.get(f"/orders/{pk}")
        assert get_resp.json()["pk"] == pk


# ---------------------------------------------------------------------------
# POST /orders
# ---------------------------------------------------------------------------

class TestCreateOrder:

    def test_create_order_returns_200(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 2}
            )
        assert response.status_code == 200

    def test_create_order_status_is_pending(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 1}
            )
        assert response.json()["status"] == "pending"

    def test_create_order_product_id_matches_request(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 1}
            )
        assert response.json()["product_id"] == inventory_product["pk"]

    def test_create_order_fee_is_20_percent_of_price(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 1}
            )
        data = response.json()
        expected_fee = 0.2 * inventory_product["price"]
        assert data["fee"] == pytest.approx(expected_fee)

    def test_create_order_total_is_correct(self, client, inventory_product):
        quantity = 3
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": quantity}
            )
        data = response.json()
        expected_total = 1.2 * inventory_product["price"] * quantity
        assert data["total"] == pytest.approx(expected_total)

    def test_create_order_quantity_matches_request(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 5}
            )
        assert response.json()["quantity"] == 5

    def test_create_order_response_has_pk(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            response = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 1}
            )
        assert "pk" in response.json()

    def test_create_order_product_not_found_returns_400(self, client):
        with _mock_inventory_not_found():
            response = client.post(
                "/orders", json={"id": "nonexistent-product", "quantity": 1}
            )
        assert response.status_code == 400

    def test_create_order_product_not_found_has_detail(self, client):
        with _mock_inventory_not_found():
            response = client.post(
                "/orders", json={"id": "ghost-product", "quantity": 2}
            )
        assert "detail" in response.json()


# ---------------------------------------------------------------------------
# Full flow: create → retrieve
# ---------------------------------------------------------------------------

class TestOrderFlow:

    def test_created_order_is_retrievable(self, client, inventory_product):
        with _mock_inventory(inventory_product):
            create_resp = client.post(
                "/orders", json={"id": inventory_product["pk"], "quantity": 2}
            )
        assert create_resp.status_code == 200
        created = create_resp.json()

        get_resp = client.get(f"/orders/{created['pk']}")
        assert get_resp.status_code == 200

        retrieved = get_resp.json()
        assert retrieved["product_id"] == created["product_id"]
        assert retrieved["price"] == pytest.approx(created["price"])
        assert retrieved["fee"] == pytest.approx(created["fee"])
        assert retrieved["total"] == pytest.approx(created["total"])
        assert retrieved["quantity"] == created["quantity"]
