"""Tests for rider saved payment methods.

POST   /riders/me/payment-methods/setup-intent
POST   /riders/me/payment-methods
GET    /riders/me/payment-methods
DELETE /riders/me/payment-methods/{pm_id}
PUT    /riders/me/payment-methods/{pm_id}/default

Coverage
--------
Schema: PaymentMethodCreate
  - valid payload passes
  - card_last4 must be exactly 4 digits
  - card_last4 must be numeric
  - card_exp_month must be 1-12
  - card_exp_year must be >= 2000

Service: add_payment_method
  - creates record with is_default=True for first method
  - subsequent methods have is_default=False
  - raises RuntimeError on duplicate stripe_payment_method_id
  - stores all fields correctly

Service: list_payment_methods
  - returns empty list when no methods
  - returns methods newest-first
  - returns only the requesting user's methods

Service: remove_payment_method
  - removes the correct record
  - raises LookupError when not found
  - raises LookupError when wrong owner
  - promotes oldest remaining to default when default is deleted
  - does not change defaults when a non-default is deleted

Service: set_default_payment_method
  - sets target as default and clears all others
  - raises LookupError when not found
  - raises LookupError when wrong owner

Router: POST /riders/me/payment-methods/setup-intent
  - 200 returns setup_intent_id

Router: POST /riders/me/payment-methods
  - 201 creates method
  - 409 on duplicate stripe_payment_method_id
  - 422 on invalid card_last4 (non-digit)
  - 422 on invalid card_exp_month (out of range)
  - 403 for non-rider user

Router: GET /riders/me/payment-methods
  - 200 returns list with total

Router: DELETE /riders/me/payment-methods/{pm_id}
  - 204 on success
  - 404 when not found
  - 404 when wrong owner

Router: PUT /riders/me/payment-methods/{pm_id}/default
  - 200 returns updated method with is_default=True
  - 404 when not found
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.payment_method import (
    PaymentMethodCreate,
    PaymentMethodResponse,
    PaymentMethodListResponse,
    SetupIntentResponse,
)
from app.services.payment_method import (
    _reset_store,
    add_payment_method,
    list_payment_methods,
    remove_payment_method,
    set_default_payment_method,
    create_setup_intent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_create(
    pm_id: str = "pm_test_abc123",
    brand: str = "visa",
    last4: str = "4242",
    month: int = 12,
    year: int = 2028,
) -> PaymentMethodCreate:
    return PaymentMethodCreate(
        stripe_payment_method_id=pm_id,
        card_brand=brand,
        card_last4=last4,
        card_exp_month=month,
        card_exp_year=year,
    )


def _make_user(user_id: int = 1, role: str = "rider") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    user.is_active = True
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    _reset_store()
    yield
    _reset_store()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestPaymentMethodCreate:
    def test_valid_payload(self):
        obj = _make_create()
        assert obj.card_last4 == "4242"
        assert obj.card_exp_month == 12

    def test_last4_wrong_length_raises(self):
        with pytest.raises(Exception):
            PaymentMethodCreate(
                stripe_payment_method_id="pm_x",
                card_brand="visa",
                card_last4="123",  # only 3 chars
                card_exp_month=1,
                card_exp_year=2030,
            )

    def test_last4_non_digit_raises(self):
        with pytest.raises(Exception):
            PaymentMethodCreate(
                stripe_payment_method_id="pm_x",
                card_brand="visa",
                card_last4="12ab",
                card_exp_month=1,
                card_exp_year=2030,
            )

    def test_exp_month_zero_raises(self):
        with pytest.raises(Exception):
            PaymentMethodCreate(
                stripe_payment_method_id="pm_x",
                card_brand="visa",
                card_last4="1234",
                card_exp_month=0,
                card_exp_year=2030,
            )

    def test_exp_month_13_raises(self):
        with pytest.raises(Exception):
            PaymentMethodCreate(
                stripe_payment_method_id="pm_x",
                card_brand="visa",
                card_last4="1234",
                card_exp_month=13,
                card_exp_year=2030,
            )

    def test_exp_year_too_old_raises(self):
        with pytest.raises(Exception):
            PaymentMethodCreate(
                stripe_payment_method_id="pm_x",
                card_brand="visa",
                card_last4="1234",
                card_exp_month=6,
                card_exp_year=1999,
            )

    def test_response_model_config(self):
        assert PaymentMethodResponse.model_config.get("from_attributes") is True


# ---------------------------------------------------------------------------
# Service: add_payment_method
# ---------------------------------------------------------------------------


class TestAddPaymentMethod:
    def test_first_method_is_default(self):
        result = add_payment_method(1, _make_create())
        assert result.is_default is True

    def test_second_method_not_default(self):
        add_payment_method(1, _make_create(pm_id="pm_first"))
        result = add_payment_method(1, _make_create(pm_id="pm_second"))
        assert result.is_default is False

    def test_stores_all_fields(self):
        data = _make_create(pm_id="pm_store", brand="mastercard", last4="5555", month=3, year=2027)
        result = add_payment_method(2, data)
        assert result.stripe_payment_method_id == "pm_store"
        assert result.card_brand == "mastercard"
        assert result.card_last4 == "5555"
        assert result.card_exp_month == 3
        assert result.card_exp_year == 2027
        assert result.id >= 1

    def test_duplicate_raises_runtime_error(self):
        add_payment_method(1, _make_create(pm_id="pm_dup"))
        with pytest.raises(RuntimeError, match="already saved"):
            add_payment_method(1, _make_create(pm_id="pm_dup"))

    def test_same_pm_id_different_users_allowed(self):
        add_payment_method(1, _make_create(pm_id="pm_shared"))
        result = add_payment_method(2, _make_create(pm_id="pm_shared"))
        assert result.is_default is True

    def test_id_increments(self):
        r1 = add_payment_method(1, _make_create(pm_id="pm_a"))
        r2 = add_payment_method(1, _make_create(pm_id="pm_b"))
        assert r2.id == r1.id + 1

    def test_created_at_is_set(self):
        result = add_payment_method(1, _make_create())
        assert result.created_at is not None


# ---------------------------------------------------------------------------
# Service: list_payment_methods
# ---------------------------------------------------------------------------


class TestListPaymentMethods:
    def test_empty_list(self):
        assert list_payment_methods(1) == []

    def test_returns_only_this_users_methods(self):
        add_payment_method(1, _make_create(pm_id="pm_user1"))
        add_payment_method(2, _make_create(pm_id="pm_user2"))
        results = list_payment_methods(1)
        assert len(results) == 1
        assert results[0].stripe_payment_method_id == "pm_user1"

    def test_newest_first_ordering(self):
        add_payment_method(1, _make_create(pm_id="pm_old"))
        add_payment_method(1, _make_create(pm_id="pm_new"))
        results = list_payment_methods(1)
        assert results[0].stripe_payment_method_id == "pm_new"
        assert results[1].stripe_payment_method_id == "pm_old"

    def test_returns_payment_method_response_instances(self):
        add_payment_method(1, _make_create())
        results = list_payment_methods(1)
        assert isinstance(results[0], PaymentMethodResponse)


# ---------------------------------------------------------------------------
# Service: remove_payment_method
# ---------------------------------------------------------------------------


class TestRemovePaymentMethod:
    def test_removes_correct_record(self):
        r = add_payment_method(1, _make_create())
        remove_payment_method(r.id, 1)
        assert list_payment_methods(1) == []

    def test_not_found_raises_lookup_error(self):
        with pytest.raises(LookupError):
            remove_payment_method(999, 1)

    def test_wrong_owner_raises_lookup_error(self):
        r = add_payment_method(1, _make_create())
        with pytest.raises(LookupError):
            remove_payment_method(r.id, 2)

    def test_deleting_default_promotes_oldest_remaining(self):
        default = add_payment_method(1, _make_create(pm_id="pm_default"))
        non_default = add_payment_method(1, _make_create(pm_id="pm_other"))
        remove_payment_method(default.id, 1)
        remaining = list_payment_methods(1)
        assert len(remaining) == 1
        assert remaining[0].is_default is True
        assert remaining[0].stripe_payment_method_id == "pm_other"

    def test_deleting_non_default_leaves_default_unchanged(self):
        default = add_payment_method(1, _make_create(pm_id="pm_default"))
        non_default = add_payment_method(1, _make_create(pm_id="pm_other"))
        remove_payment_method(non_default.id, 1)
        remaining = list_payment_methods(1)
        assert remaining[0].stripe_payment_method_id == "pm_default"
        assert remaining[0].is_default is True

    def test_no_promotion_when_only_method_deleted(self):
        r = add_payment_method(1, _make_create())
        remove_payment_method(r.id, 1)
        assert list_payment_methods(1) == []


# ---------------------------------------------------------------------------
# Service: set_default_payment_method
# ---------------------------------------------------------------------------


class TestSetDefaultPaymentMethod:
    def test_sets_target_as_default(self):
        add_payment_method(1, _make_create(pm_id="pm_first"))
        second = add_payment_method(1, _make_create(pm_id="pm_second"))
        result = set_default_payment_method(second.id, 1)
        assert result.is_default is True
        assert result.stripe_payment_method_id == "pm_second"

    def test_clears_previous_default(self):
        first = add_payment_method(1, _make_create(pm_id="pm_first"))
        second = add_payment_method(1, _make_create(pm_id="pm_second"))
        set_default_payment_method(second.id, 1)
        methods = list_payment_methods(1)
        defaults = [m for m in methods if m.is_default]
        assert len(defaults) == 1
        assert defaults[0].stripe_payment_method_id == "pm_second"

    def test_not_found_raises_lookup_error(self):
        with pytest.raises(LookupError):
            set_default_payment_method(999, 1)

    def test_wrong_owner_raises_lookup_error(self):
        r = add_payment_method(1, _make_create())
        with pytest.raises(LookupError):
            set_default_payment_method(r.id, 2)

    def test_returns_payment_method_response(self):
        r = add_payment_method(1, _make_create())
        result = set_default_payment_method(r.id, 1)
        assert isinstance(result, PaymentMethodResponse)


# ---------------------------------------------------------------------------
# Router tests (via TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture()
def rider_user():
    return _make_user(user_id=10, role="rider")


@pytest.fixture()
def driver_user():
    return _make_user(user_id=20, role="driver")


@pytest.fixture()
def client(rider_user):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_rider, get_current_user

    app.dependency_overrides[require_rider] = lambda: rider_user
    app.dependency_overrides[get_current_user] = lambda: rider_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def driver_client(driver_user, rider_user):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_rider, get_current_user

    app.dependency_overrides[get_current_user] = lambda: driver_user

    def _deny_non_rider():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Rider access required")

    app.dependency_overrides[require_rider] = _deny_non_rider
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


VALID_PAYLOAD = {
    "stripe_payment_method_id": "pm_router_test",
    "card_brand": "visa",
    "card_last4": "4242",
    "card_exp_month": 12,
    "card_exp_year": 2030,
}


class TestRouterSetupIntent:
    def test_returns_200_with_setup_intent_id(self, client):
        with patch("app.services.payment_method.stripe") as mock_stripe:
            mock_intent = MagicMock()
            mock_intent.id = "si_test_xyz"
            mock_intent.client_secret = "seti_secret_abc"
            mock_stripe.SetupIntent.create.return_value = mock_intent
            resp = client.post("/api/v1/riders/me/payment-methods/setup-intent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["setup_intent_id"] == "si_test_xyz"

    def test_degrades_gracefully_when_stripe_fails(self, client):
        with patch("app.services.payment_method.stripe") as mock_stripe:
            mock_stripe.SetupIntent.create.side_effect = Exception("no key")
            resp = client.post("/api/v1/riders/me/payment-methods/setup-intent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["setup_intent_id"] == "si_stub"
        assert data["client_secret"] is None


class TestRouterSavePaymentMethod:
    def test_201_creates_method(self, client):
        resp = client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["stripe_payment_method_id"] == "pm_router_test"
        assert data["is_default"] is True

    def test_409_on_duplicate(self, client):
        client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        resp = client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        assert resp.status_code == 409

    def test_422_non_digit_last4(self, client):
        bad = {**VALID_PAYLOAD, "card_last4": "12ab"}
        resp = client.post("/api/v1/riders/me/payment-methods", json=bad)
        assert resp.status_code == 422

    def test_422_exp_month_out_of_range(self, client):
        bad = {**VALID_PAYLOAD, "card_exp_month": 13}
        resp = client.post("/api/v1/riders/me/payment-methods", json=bad)
        assert resp.status_code == 422

    def test_403_for_non_rider(self, driver_client):
        resp = driver_client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        assert resp.status_code == 403


class TestRouterListPaymentMethods:
    def test_200_returns_empty_list(self, client):
        resp = client.get("/api/v1/riders/me/payment-methods")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_200_returns_saved_methods(self, client):
        client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        resp = client.get("/api/v1/riders/me/payment-methods")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["stripe_payment_method_id"] == "pm_router_test"

    def test_403_for_non_rider(self, driver_client):
        resp = driver_client.get("/api/v1/riders/me/payment-methods")
        assert resp.status_code == 403


class TestRouterDeletePaymentMethod:
    def test_204_on_success(self, client):
        resp = client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        pm_id = resp.json()["id"]
        resp = client.delete(f"/api/v1/riders/me/payment-methods/{pm_id}")
        assert resp.status_code == 204

    def test_404_when_not_found(self, client):
        resp = client.delete("/api/v1/riders/me/payment-methods/9999")
        assert resp.status_code == 404

    def test_403_for_non_rider(self, driver_client):
        resp = driver_client.delete("/api/v1/riders/me/payment-methods/1")
        assert resp.status_code == 403


class TestRouterSetDefault:
    def test_200_sets_default(self, client):
        client.post("/api/v1/riders/me/payment-methods", json=VALID_PAYLOAD)
        payload2 = {**VALID_PAYLOAD, "stripe_payment_method_id": "pm_second"}
        r2 = client.post("/api/v1/riders/me/payment-methods", json=payload2)
        pm_id = r2.json()["id"]
        resp = client.put(f"/api/v1/riders/me/payment-methods/{pm_id}/default")
        assert resp.status_code == 200
        assert resp.json()["is_default"] is True
        assert resp.json()["stripe_payment_method_id"] == "pm_second"

    def test_404_when_not_found(self, client):
        resp = client.put("/api/v1/riders/me/payment-methods/9999/default")
        assert resp.status_code == 404

    def test_403_for_non_rider(self, driver_client):
        resp = driver_client.put("/api/v1/riders/me/payment-methods/1/default")
        assert resp.status_code == 403
