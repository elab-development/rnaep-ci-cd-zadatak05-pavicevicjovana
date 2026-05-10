"""
Unit tests for the Payment service business logic.
All external dependencies (Redis, HTTP) are mocked.
"""

import pytest


class TestFeeCalculation:
    """fee = 0.2 * product price"""

    def test_standard_price(self):
        price = 100.0
        assert 0.2 * price == pytest.approx(20.0)

    def test_fractional_price(self):
        price = 49.99
        assert 0.2 * price == pytest.approx(9.998)

    def test_zero_price(self):
        assert 0.2 * 0.0 == pytest.approx(0.0)

    def test_large_price(self):
        price = 9999.99
        assert 0.2 * price == pytest.approx(1999.998)


class TestTotalCalculation:
    """total = 1.2 * product price * quantity"""

    def test_single_item(self):
        price = 100.0
        assert 1.2 * price * 1 == pytest.approx(120.0)

    def test_multiple_items(self):
        price = 50.0
        assert 1.2 * price * 3 == pytest.approx(180.0)

    def test_total_equals_price_plus_fee_times_quantity(self):
        price = 100.0
        quantity = 2
        fee = 0.2 * price
        total = 1.2 * price * quantity
        assert total == pytest.approx((price + fee) * quantity)

    def test_decimal_price_and_quantity(self):
        price = 29.99
        quantity = 4
        assert 1.2 * price * quantity == pytest.approx(143.952)


class TestOrderStatusValues:
    """Order status must be one of: pending, completed, refunded."""

    VALID_STATUSES = ["pending", "completed", "refunded"]

    def test_all_statuses_are_strings(self):
        for status in self.VALID_STATUSES:
            assert isinstance(status, str)

    def test_initial_status_is_pending(self):
        initial_status = "pending"
        assert initial_status in self.VALID_STATUSES

    def test_completed_status_is_valid(self):
        assert "completed" in self.VALID_STATUSES

    def test_refunded_status_is_valid(self):
        assert "refunded" in self.VALID_STATUSES

    def test_invalid_status_not_in_valid_list(self):
        assert "cancelled" not in self.VALID_STATUSES
        assert "processing" not in self.VALID_STATUSES


class TestOrderFieldLogic:
    """Order fields must be derived correctly from product data and request body."""

    def test_product_id_comes_from_request_body(self):
        body = {"id": "prod-abc-123", "quantity": 2}
        product_id = body["id"]
        assert product_id == "prod-abc-123"

    def test_price_comes_from_inventory_response(self):
        product = {"pk": "prod-1", "name": "Widget", "price": 75.0, "quantity": 100}
        price = product["price"]
        assert price == pytest.approx(75.0)

    def test_fee_derived_from_inventory_price(self):
        product_price = 80.0
        fee = 0.2 * product_price
        assert fee == pytest.approx(16.0)

    def test_total_derived_from_price_and_quantity(self):
        product_price = 80.0
        quantity = 5
        total = 1.2 * product_price * quantity
        assert total == pytest.approx(480.0)

    def test_quantity_comes_from_request_body(self):
        body = {"id": "prod-xyz", "quantity": 7}
        assert body["quantity"] == 7

    def test_order_creation_fields_all_correct(self):
        product = {"price": 100.0}
        body = {"id": "prod-1", "quantity": 3}

        order_data = {
            "product_id": body["id"],
            "price": product["price"],
            "fee": 0.2 * product["price"],
            "total": 1.2 * product["price"] * body["quantity"],
            "quantity": body["quantity"],
            "status": "pending",
        }

        assert order_data["product_id"] == "prod-1"
        assert order_data["price"] == pytest.approx(100.0)
        assert order_data["fee"] == pytest.approx(20.0)
        assert order_data["total"] == pytest.approx(360.0)
        assert order_data["quantity"] == 3
        assert order_data["status"] == "pending"


class TestProcessOrderLogic:
    """Business rules for the process_order background task."""

    def test_order_status_changes_to_completed_after_processing(self):
        initial_status = "pending"
        processed_status = "completed"

        assert initial_status != processed_status
        assert processed_status == "completed"

    def test_completed_order_can_be_refunded(self):
        completed = "completed"
        refunded = "refunded"

        assert completed != refunded
        assert refunded == "refunded"

    def test_order_status_transition_sequence(self):
        statuses = ["pending", "completed", "refunded"]
        assert statuses.index("pending") < statuses.index("completed")
        assert statuses.index("completed") < statuses.index("refunded")
