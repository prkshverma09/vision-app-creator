"""CT-ACTIONS: review gates, idempotent outbox, bounded retry, and SSRF safety."""
import pytest
from vision_app.actions import (
    ActionContext,
    ActionService,
    DeliveryState,
    Destination,
    DestinationSafetyError,
    InMemoryDeliveryStore,
    InMemoryWebhookSink,
    Permission,
    RetryBudgetExhausted,
    SafeWebhookTransport,
    StaticResolver,
    eligibility,
)


def context(**changes: object) -> ActionContext:
    values = {
        "workspace_id": "workspace-1",
        "event_id": "event-1",
        "event_revision": 3,
        "machine_decision": "supported",
        "human_review": "confirmed_by_user",
        "selected_finalized": True,
        "run_mode": "normal",
        "action_ref": "permission-1",
        "explicitly_enabled": True,
        "deleted": False,
        "cancelled": False,
        "budget_available": True,
    }
    values.update(changes)
    return ActionContext(**values)


def permission(**changes: object) -> Permission:
    values = {
        "id": "permission-1",
        "version": 2,
        "workspace_id": "workspace-1",
        "destination_ref": "destination-1",
        "enabled": True,
        "preapproved": False,
    }
    values.update(changes)
    return Permission(**values)


def test_unreviewed_event_and_preview_produce_zero_requests() -> None:
    assert not eligibility(context(human_review="unreviewed"), permission()).eligible
    assert not eligibility(context(run_mode="preview"), permission()).eligible


def test_preapproval_is_explicit_exception_to_human_review() -> None:
    result = eligibility(context(human_review="unreviewed"), permission(preapproved=True))
    assert result.eligible


def test_enablement_version_workspace_and_revocation_are_required() -> None:
    assert not eligibility(context(explicitly_enabled=False), permission()).eligible
    assert not eligibility(context(action_ref="other"), permission()).eligible
    assert not eligibility(context(workspace_id="other"), permission()).eligible
    assert not eligibility(context(event_revision=4), permission(), reviewed_revision=3).eligible
    assert not eligibility(context(), permission(enabled=False)).eligible


@pytest.mark.asyncio
async def test_duplicate_outbox_entries_are_idempotent_and_payload_supports_dedup() -> None:
    store = InMemoryDeliveryStore()
    sink = InMemoryWebhookSink()
    service = ActionService(store, sink, signing_secret=b"secret", max_attempts=3)
    first = await service.enqueue(context(), permission())
    duplicate = await service.enqueue(context(), permission())

    assert first.id == duplicate.id
    assert len(store.records) == 1
    delivered = await service.deliver(first.id, context(), permission())
    delivered_again = await service.deliver(first.id, context(), permission())
    assert delivered.state is DeliveryState.DELIVERED
    assert delivered_again.state is DeliveryState.DELIVERED
    assert len(sink.requests) == 1
    assert sink.requests[0].payload["delivery_id"] == first.id
    assert sink.requests[0].payload["event_id"] == "event-1"
    assert sink.requests[0].signature.startswith("sha256=")


@pytest.mark.asyncio
async def test_revoked_permission_suppresses_pending_delivery() -> None:
    store = InMemoryDeliveryStore()
    sink = InMemoryWebhookSink()
    service = ActionService(store, sink, signing_secret=b"secret")
    record = await service.enqueue(context(), permission())
    suppressed = await service.deliver(record.id, context(), permission(enabled=False))
    assert suppressed.state is DeliveryState.SUPPRESSED
    assert sink.requests == []


@pytest.mark.asyncio
async def test_retry_budget_is_enforced_and_status_tracked() -> None:
    store = InMemoryDeliveryStore()
    sink = InMemoryWebhookSink(failures=3)
    service = ActionService(store, sink, signing_secret=b"secret", max_attempts=2)
    record = await service.enqueue(context(), permission())

    with pytest.raises(ConnectionError):
        await service.deliver(record.id, context(), permission())
    with pytest.raises(ConnectionError):
        await service.deliver(record.id, context(), permission())
    with pytest.raises(RetryBudgetExhausted):
        await service.deliver(record.id, context(), permission())
    assert store.records[record.id].state is DeliveryState.EXHAUSTED
    assert store.records[record.id].attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.4", "169.254.169.254", "::1"])
async def test_unsafe_destination_is_rejected_without_http(address: str) -> None:
    sink = InMemoryWebhookSink()
    transport = SafeWebhookTransport(
        {"destination-1": Destination("destination-1", "https://hooks.example.test/action")},
        StaticResolver({"hooks.example.test": [address]}),
        sink,
    )
    with pytest.raises(DestinationSafetyError):
        await transport.send("destination-1", b"{}", "sha256=x")
    assert sink.requests == []


@pytest.mark.asyncio
async def test_mixed_dns_and_redirects_are_rejected() -> None:
    sink = InMemoryWebhookSink(redirect_url="https://internal.example.test/hook")
    mixed = SafeWebhookTransport(
        {"destination-1": Destination("destination-1", "https://hooks.example.test/action")},
        StaticResolver({"hooks.example.test": ["93.184.216.34", "127.0.0.1"]}),
        sink,
    )
    with pytest.raises(DestinationSafetyError):
        await mixed.send("destination-1", b"{}", "sha256=x")

    redirect = SafeWebhookTransport(
        {"destination-1": Destination("destination-1", "https://hooks.example.test/action")},
        StaticResolver({"hooks.example.test": ["93.184.216.34"]}),
        sink,
    )
    with pytest.raises(DestinationSafetyError):
        await redirect.send("destination-1", b"{}", "sha256=x")


def test_destination_rejects_scheme_credentials_and_non_allowlisted_endpoint() -> None:
    with pytest.raises(ValueError):
        Destination("x", "http://example.test/hook")
    with pytest.raises(ValueError):
        Destination("x", "https://user:pass@example.test/hook")
    with pytest.raises(DestinationSafetyError):
        SafeWebhookTransport(
            {"x": Destination("x", "https://example.test/hook")},
            StaticResolver({"example.test": ["93.184.216.34"]}),
            InMemoryWebhookSink(),
            allowed_destination_refs=frozenset({"approved-demo"}),
        )


def test_dry_run_has_zero_network() -> None:
    store = InMemoryDeliveryStore()
    sink = InMemoryWebhookSink()
    service = ActionService(store, sink, signing_secret=b"secret")
    preview = service.preview(context())
    assert preview["event_id"] == "event-1"
    assert store.records == {}
    assert sink.requests == []
