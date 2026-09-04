"""Billing tests — Stripe Checkout, webhook signature verification and
event handling, invoice history, and the platform-admin manual
subscription override. All Stripe API calls are mocked via a fake
StripeClient injected through FastAPI's dependency_overrides; webhook
signature verification uses the REAL stripe SDK's local HMAC signing/
verification (no network call either way — this is pure local
cryptography, so it's tested for real, not mocked).

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import contextlib
import json
import uuid

import pytest
import stripe
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.billing import _get_service as _billing_get_service
from app.api.v1.platform import _get_billing_service as _platform_get_billing_service
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import User
from app.models.subscription import Subscription
from app.services.billing import BillingService
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Billing Tester"):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": full_name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _login(email: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup_token() -> str:
    return _login(_register(_email(f"user{uuid.uuid4().hex[:6]}"))["email"])


async def _promote_platform_admin(user_id: int) -> None:
    async with TestSessionLocal() as session:
        user = await session.get(User, user_id)
        user.is_platform_admin = True
        await session.commit()


def _setup_admin_token() -> str:
    email = _email(f"admin{uuid.uuid4().hex[:6]}")
    user = _register(email)
    asyncio.run(_promote_platform_admin(user["id"]))
    return _login(email)


def _create_org(token: str, name: str = "Org") -> int:
    r = client.post(
        "/api/v1/organizations",
        json={"name": name, "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(token: str, org_id: int, email: str, role: str = "member"):
    r = client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _get_subscription_row(organization_id: int) -> Subscription | None:
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )
        return result.scalar_one_or_none()


async def _get_organization_disabled_state(organization_id: int) -> tuple[bool, str | None]:
    from app.models import Organization

    async with TestSessionLocal() as session:
        org = await session.get(Organization, organization_id)
        return org.disabled_at is not None, org.disabled_message


class FakeStripeClient:
    """Records every call; never touches the network."""

    def __init__(self, checkout_url: str = "https://checkout.stripe.com/fake-session", invoices=None):
        self.checkout_url = checkout_url
        self.invoices = invoices if invoices is not None else []
        self.checkout_calls: list[dict] = []
        self.invoice_calls: list[str] = []

    def create_checkout_session(self, *, customer_id, customer_email, price_id, success_url, cancel_url, metadata):
        self.checkout_calls.append(
            dict(
                customer_id=customer_id,
                customer_email=customer_email,
                price_id=price_id,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata,
            )
        )
        return self.checkout_url

    def list_invoices(self, *, customer_id):
        self.invoice_calls.append(customer_id)
        return self.invoices


@contextlib.contextmanager
def _swap_stripe_client(fake_client: FakeStripeClient):
    """Injects a fake StripeClient wherever BillingService is constructed
    via FastAPI DI — the checkout/invoice/manual-override routes. No real
    Stripe network call can occur while this is active."""

    async def override(db: AsyncSession = Depends(get_db)) -> BillingService:
        return BillingService(db, stripe_client=fake_client)

    app.dependency_overrides[_billing_get_service] = override
    app.dependency_overrides[_platform_get_billing_service] = override
    try:
        yield
    finally:
        app.dependency_overrides.pop(_billing_get_service, None)
        app.dependency_overrides.pop(_platform_get_billing_service, None)


def _webhook_request(event: dict) -> object:
    payload = json.dumps(event).encode()
    sig_header = stripe.WebhookSignature.generate_signature_header(
        payload.decode(), settings.stripe_webhook_secret
    )
    return client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"content-type": "application/json", "stripe-signature": sig_header},
    )


def _checkout_completed_event(organization_id: int, tier: str, customer_id: str, subscription_id: str) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{uuid.uuid4().hex[:12]}",
                "customer": customer_id,
                "subscription": subscription_id,
                "metadata": {"organization_id": str(organization_id), "tier": tier},
            }
        },
    }


def _subscription_updated_event(stripe_subscription_id: str, status: str, period_end: int = 1893456000) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": stripe_subscription_id,
                "status": status,
                "current_period_end": period_end,
            }
        },
    }


def _subscription_deleted_event(stripe_subscription_id: str) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": stripe_subscription_id, "status": "canceled"}},
    }


def _payment_failed_event(customer_id: str) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "invoice.payment_failed",
        "data": {"object": {"id": f"in_{uuid.uuid4().hex[:12]}", "customer": customer_id}},
    }


# --- checkout ---


def test_checkout_owner_can_initiate_no_local_row_created() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.post(
            f"/api/v1/organizations/{org_id}/billing/checkout",
            json={"tier": "pro"},
            headers=_auth(token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"] == fake.checkout_url
    assert len(fake.checkout_calls) == 1
    call = fake.checkout_calls[0]
    assert call["price_id"] == settings.stripe_price_id_pro
    assert call["metadata"] == {"organization_id": str(org_id), "tier": "pro"}
    assert call["customer_id"] is None  # no prior subscription row to reuse a customer from

    # This endpoint alone must never mutate the subscriptions table.
    assert asyncio.run(_get_subscription_row(org_id)) is None


def test_checkout_non_owner_403() -> None:
    owner_token = _setup_token()
    org_id = _create_org(owner_token)
    member_email = _email(f"member{uuid.uuid4().hex[:6]}")
    member_token = _login(_register(member_email)["email"])
    _add_member(owner_token, org_id, member_email, role="member")

    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.post(
            f"/api/v1/organizations/{org_id}/billing/checkout",
            json={"tier": "pro"},
            headers=_auth(member_token),
        )
    assert r.status_code == 403
    assert fake.checkout_calls == []


def test_checkout_admin_role_403() -> None:
    """ADMIN is not OWNER — this is a financial commitment, same bar as
    organization deletion."""
    owner_token = _setup_token()
    org_id = _create_org(owner_token)
    admin_email = _email(f"orgadmin{uuid.uuid4().hex[:6]}")
    admin_token = _login(_register(admin_email)["email"])
    _add_member(owner_token, org_id, admin_email, role="admin")

    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.post(
            f"/api/v1/organizations/{org_id}/billing/checkout",
            json={"tier": "pro"},
            headers=_auth(admin_token),
        )
    assert r.status_code == 403


def test_checkout_unknown_tier_422() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.post(
            f"/api/v1/organizations/{org_id}/billing/checkout",
            json={"tier": "not-a-real-tier"},
            headers=_auth(token),
        )
    assert r.status_code == 422
    assert fake.checkout_calls == []


def test_checkout_reuses_existing_stripe_customer_id() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    admin_token = _setup_admin_token()
    # Seed a subscription row (as if a prior checkout/webhook happened).
    r = client.patch(
        f"/api/v1/platform/organizations/{org_id}/subscription",
        json={"tier": "pro", "status": "active"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    async def _set_customer_id():
        async with TestSessionLocal() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.organization_id == org_id)
            )
            sub = result.scalar_one()
            sub.stripe_customer_id = "cus_existing_123"
            await session.commit()

    asyncio.run(_set_customer_id())

    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.post(
            f"/api/v1/organizations/{org_id}/billing/checkout",
            json={"tier": "enterprise"},
            headers=_auth(token),
        )
    assert r.status_code == 200, r.text
    assert fake.checkout_calls[0]["customer_id"] == "cus_existing_123"


# --- webhook: signature verification ---


def test_webhook_valid_signature_processed() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    event = _checkout_completed_event(org_id, "pro", "cus_sig_ok", "sub_sig_ok")
    r = _webhook_request(event)
    assert r.status_code == 200, r.text
    sub = asyncio.run(_get_subscription_row(org_id))
    assert sub is not None
    assert sub.tier == "pro"
    assert sub.status == "active"


def test_webhook_missing_signature_rejected_before_business_logic() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    event = _checkout_completed_event(org_id, "pro", "cus_no_sig", "sub_no_sig")
    r = client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event).encode(),
        headers={"content-type": "application/json"},  # no stripe-signature
    )
    assert r.status_code == 400
    assert asyncio.run(_get_subscription_row(org_id)) is None


def test_webhook_invalid_signature_rejected_before_business_logic() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    event = _checkout_completed_event(org_id, "pro", "cus_bad_sig", "sub_bad_sig")
    payload = json.dumps(event).encode()
    bad_sig = stripe.WebhookSignature.generate_signature_header(
        payload.decode(), "wrong_secret_entirely"
    )
    r = client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"content-type": "application/json", "stripe-signature": bad_sig},
    )
    assert r.status_code == 400
    assert asyncio.run(_get_subscription_row(org_id)) is None


# --- webhook: event handling ---


def test_checkout_completed_upserts_subscription_row() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    event = _checkout_completed_event(org_id, "enterprise", "cus_abc", "sub_abc")
    r = _webhook_request(event)
    assert r.status_code == 200, r.text
    sub = asyncio.run(_get_subscription_row(org_id))
    assert sub.tier == "enterprise"
    assert sub.status == "active"
    assert sub.stripe_customer_id == "cus_abc"
    assert sub.stripe_subscription_id == "sub_abc"


def test_subscription_canceled_triggers_organization_disable() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    assert _webhook_request(
        _checkout_completed_event(org_id, "pro", "cus_cancel_test", stripe_sub_id)
    ).status_code == 200

    disabled_before, _ = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled_before is False

    r = _webhook_request(_subscription_updated_event(stripe_sub_id, "canceled"))
    assert r.status_code == 200, r.text

    disabled_after, message = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled_after is True
    assert message == "This organization's subscription has lapsed."

    # Enforcement matches the exact platform-dashboard mechanism: the org
    # owner's very next org-scoped request 403s.
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(token))
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_subscription_deleted_triggers_organization_disable() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    assert _webhook_request(
        _checkout_completed_event(org_id, "pro", "cus_del_test", stripe_sub_id)
    ).status_code == 200

    r = _webhook_request(_subscription_deleted_event(stripe_sub_id))
    assert r.status_code == 200, r.text
    disabled, message = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is True
    assert message == "This organization's subscription has lapsed."


def test_subscription_recovery_to_active_re_enables_organization() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    assert _webhook_request(
        _checkout_completed_event(org_id, "pro", "cus_recover_test", stripe_sub_id)
    ).status_code == 200
    assert _webhook_request(
        _subscription_updated_event(stripe_sub_id, "canceled")
    ).status_code == 200

    disabled, _ = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is True

    r = _webhook_request(_subscription_updated_event(stripe_sub_id, "active"))
    assert r.status_code == 200, r.text
    disabled_after, message_after = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled_after is False
    assert message_after is None

    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(token))
    assert r.status_code == 200, r.text


def test_recovery_never_clears_an_unrelated_manual_admin_disable() -> None:
    """Genuinely forces a canceled -> active transition so the recovery
    path's message-matching guard (_re_enable_after_recovery) actually
    runs, rather than reaching a passing state for an unrelated reason.

    A shallower version of this test (checkout -> admin disable ->
    "recovery" webhook reporting the status the subscription was
    already at) does NOT exercise the guard at all: the outer
    new_status=="active" and previous_status!="active" check
    short-circuits before the message comparison is ever reached, since
    the stored status never actually left "active". This version walks
    through a REAL cancellation first, so the subsequent recovery event
    is a genuine transition."""
    token = _setup_token()
    org_id = _create_org(token)
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:12]}"

    # 1. Real checkout -> active subscription.
    assert _webhook_request(
        _checkout_completed_event(org_id, "pro", "cus_manual_test", stripe_sub_id)
    ).status_code == 200

    # 2. Real cancellation -> genuinely triggers the billing-lapse disable
    #    path. Intermediate checkpoint: proves the setup is real, not
    #    assumed — the org must actually be disabled with the exact
    #    lapse message before we proceed.
    r = _webhook_request(_subscription_updated_event(stripe_sub_id, "canceled"))
    assert r.status_code == 200, r.text
    disabled, message = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is True
    assert message == "This organization's subscription has lapsed."

    # 3. A platform admin manually disables again with a DIFFERENT,
    #    unrelated message, via the real endpoint (not a direct DB write).
    admin_token = _setup_admin_token()
    r = client.post(
        f"/api/v1/platform/organizations/{org_id}/disable",
        json={"message": "Terms of service violation."},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    disabled, message = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is True
    assert message == "Terms of service violation."

    # 4. A genuine recovery webhook: status truly transitions
    #    canceled -> active this time (previous_status == "canceled" from
    #    step 2), so _re_enable_after_recovery is actually invoked.
    r = _webhook_request(_subscription_updated_event(stripe_sub_id, "active"))
    assert r.status_code == 200, r.text

    # 5. The org must stay disabled with the admin's message — the guard
    #    must refuse to re-enable since disabled_message != the lapse
    #    string, not silently clear an unrelated disable.
    disabled, message = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is True
    assert message == "Terms of service violation."


def test_payment_failed_never_disables_grace_period() -> None:
    """Regression-style proof of the approved grace-period decision:
    invoice.payment_failed must never trigger a disable."""
    token = _setup_token()
    org_id = _create_org(token)
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    assert _webhook_request(
        _checkout_completed_event(org_id, "pro", "cus_grace_test", stripe_sub_id)
    ).status_code == 200

    r = _webhook_request(_payment_failed_event("cus_grace_test"))
    assert r.status_code == 200, r.text

    disabled, message = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is False
    assert message is None
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(token))
    assert r.status_code == 200, r.text

    sub = asyncio.run(_get_subscription_row(org_id))
    assert sub.status == "active"  # unchanged by the payment-failed event


def test_subscription_updated_for_unknown_stripe_subscription_id_ignored() -> None:
    """A webhook for a subscription this platform never recorded (e.g. a
    stray/test event) must not crash and must not touch any org."""
    r = _webhook_request(_subscription_updated_event(f"sub_never_seen_{uuid.uuid4().hex[:8]}", "canceled"))
    assert r.status_code == 200, r.text


# --- platform-admin manual override ---


def test_manual_override_requires_platform_admin() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    r = client.patch(
        f"/api/v1/platform/organizations/{org_id}/subscription",
        json={"tier": "pro", "status": "active"},
        headers=_auth(token),
    )
    assert r.status_code == 403


def test_manual_override_creates_row_when_absent() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    assert asyncio.run(_get_subscription_row(org_id)) is None

    admin_token = _setup_admin_token()
    r = client.patch(
        f"/api/v1/platform/organizations/{org_id}/subscription",
        json={"tier": "enterprise", "status": "active"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"tier": "enterprise", "status": "active", "current_period_end": None}

    sub = asyncio.run(_get_subscription_row(org_id))
    assert sub.tier == "enterprise"
    assert sub.status == "active"
    assert sub.stripe_customer_id is None
    assert sub.stripe_subscription_id is None


def test_manual_override_then_real_webhook_overwrites_via_normal_upsert() -> None:
    """No special-casing between admin-set and Stripe-set rows — a real
    webhook event overwrites a manually-set row through the same upsert
    path used for any other organization."""
    token = _setup_token()
    org_id = _create_org(token)
    admin_token = _setup_admin_token()
    r = client.patch(
        f"/api/v1/platform/organizations/{org_id}/subscription",
        json={"tier": "pro", "status": "active"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    stripe_sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    r = _webhook_request(
        _checkout_completed_event(org_id, "enterprise", "cus_overwrite_test", stripe_sub_id)
    )
    assert r.status_code == 200, r.text

    sub = asyncio.run(_get_subscription_row(org_id))
    assert sub.tier == "enterprise"
    assert sub.stripe_customer_id == "cus_overwrite_test"
    assert sub.stripe_subscription_id == stripe_sub_id


# --- pre-existing organizations unaffected ---


def test_organization_never_touching_billing_has_no_subscription_row_and_stays_enabled() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    sub = asyncio.run(_get_subscription_row(org_id))
    assert sub is None
    disabled, _ = asyncio.run(_get_organization_disabled_state(org_id))
    assert disabled is False
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(token))
    assert r.status_code == 200, r.text


# --- invoice history ---


def test_list_invoices_owner_gated_and_queries_stripe() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    admin_token = _setup_admin_token()
    r = client.patch(
        f"/api/v1/platform/organizations/{org_id}/subscription",
        json={"tier": "pro", "status": "active"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200

    async def _set_customer_id():
        async with TestSessionLocal() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.organization_id == org_id)
            )
            sub = result.scalar_one()
            sub.stripe_customer_id = "cus_invoice_test"
            await session.commit()

    asyncio.run(_set_customer_id())

    fake_invoices = [
        {
            "id": "in_1",
            "created": 1893456000,
            "amount_paid": 2900,
            "currency": "usd",
            "status": "paid",
            "hosted_invoice_url": "https://stripe.example/in_1",
        }
    ]
    fake = FakeStripeClient(invoices=fake_invoices)
    with _swap_stripe_client(fake):
        r = client.get(f"/api/v1/organizations/{org_id}/billing/invoices", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert fake.invoice_calls == ["cus_invoice_test"]
    assert r.json()["items"][0]["id"] == "in_1"
    assert r.json()["items"][0]["amount_paid"] == 2900


def test_list_invoices_non_owner_403() -> None:
    owner_token = _setup_token()
    org_id = _create_org(owner_token)
    member_email = _email(f"invmember{uuid.uuid4().hex[:6]}")
    member_token = _login(_register(member_email)["email"])
    _add_member(owner_token, org_id, member_email, role="member")

    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.get(f"/api/v1/organizations/{org_id}/billing/invoices", headers=_auth(member_token))
    assert r.status_code == 403


def test_list_invoices_no_subscription_returns_empty() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    fake = FakeStripeClient()
    with _swap_stripe_client(fake):
        r = client.get(f"/api/v1/organizations/{org_id}/billing/invoices", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert fake.invoice_calls == []  # never even called Stripe — no customer id to query


# --- platform-wide Stripe credential settings (mirrors BYOK exactly) ---


def test_stripe_settings_requires_platform_admin() -> None:
    token = _setup_token()
    assert client.get("/api/v1/platform/settings/stripe", headers=_auth(token)).status_code == 403
    assert (
        client.put(
            "/api/v1/platform/settings/stripe",
            json={"secret_key": "sk_test_whatever"},
            headers=_auth(token),
        ).status_code
        == 403
    )


def test_stripe_settings_set_and_masked_retrieval() -> None:
    admin_token = _setup_admin_token()
    secret_key = "sk_test_abcdef1234567890WXYZ"
    r = client.put(
        "/api/v1/platform/settings/stripe",
        json={"secret_key": secret_key},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["masked_key"] == "••••••••" + secret_key[-4:]
    assert secret_key not in r.text  # the raw key is never in the response

    r = client.get("/api/v1/platform/settings/stripe", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["masked_key"] == "••••••••" + secret_key[-4:]
    assert secret_key not in r.text


def test_stripe_settings_replaces_previous_key() -> None:
    admin_token = _setup_admin_token()
    client.put(
        "/api/v1/platform/settings/stripe",
        json={"secret_key": "sk_test_first0000"},
        headers=_auth(admin_token),
    )
    second_key = "sk_test_second9999"
    r = client.put(
        "/api/v1/platform/settings/stripe",
        json={"secret_key": second_key},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["masked_key"] == "••••••••" + second_key[-4:]
