"""Idempotent action outbox and bounded delivery processor."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import replace
from typing import Any

from vision_app.contracts.ports import WebhookTransport

from .eligibility import eligibility
from .models import ActionContext, DeliveryRecord, DeliveryState, Permission


class ActionNotEligible(RuntimeError):
    pass


class RetryBudgetExhausted(RuntimeError):
    pass


class InMemoryDeliveryStore:
    """Atomic in-memory outbox fake used by component tests."""

    def __init__(self) -> None:
        self.records: dict[str, DeliveryRecord] = {}
        self._lock = asyncio.Lock()

    async def create_once(self, record: DeliveryRecord) -> DeliveryRecord:
        async with self._lock:
            return self.records.setdefault(record.id, record)

    async def get(self, delivery_id: str) -> DeliveryRecord:
        async with self._lock:
            return self.records[delivery_id]

    async def put(self, record: DeliveryRecord) -> None:
        async with self._lock:
            self.records[record.id] = record


class ActionService:
    def __init__(
        self,
        store: InMemoryDeliveryStore,
        transport: WebhookTransport,
        *,
        signing_secret: bytes,
        max_attempts: int = 3,
        max_payload_bytes: int = 64_000,
    ) -> None:
        if not signing_secret:
            raise ValueError("signing_secret is required")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._store = store
        self._transport = transport
        self._secret = signing_secret
        self._max_attempts = max_attempts
        self._max_payload_bytes = max_payload_bytes

    def preview(self, context: ActionContext) -> dict[str, Any]:
        return {
            "event_id": context.event_id,
            "event_revision": context.event_revision,
            "dry_run": True,
        }

    async def enqueue(
        self,
        context: ActionContext,
        permission: Permission,
        *,
        reviewed_revision: int | None = None,
    ) -> DeliveryRecord:
        decision = eligibility(context, permission, reviewed_revision=reviewed_revision)
        if not decision.eligible:
            raise ActionNotEligible(",".join(decision.reasons))
        key = self.delivery_key(context, permission)
        return await self._store.create_once(
            DeliveryRecord(
                id=key,
                event_id=context.event_id,
                event_revision=context.event_revision,
                destination_ref=permission.destination_ref,
                permission_id=permission.id,
                permission_version=permission.version,
            )
        )

    async def deliver(
        self, delivery_id: str, context: ActionContext, permission: Permission
    ) -> DeliveryRecord:
        record = await self._store.get(delivery_id)
        if record.state in {DeliveryState.DELIVERED, DeliveryState.SUPPRESSED}:
            return record
        decision = eligibility(context, permission)
        expected_key = self.delivery_key(context, permission)
        if not decision.eligible or expected_key != record.id:
            suppressed = replace(record, state=DeliveryState.SUPPRESSED)
            await self._store.put(suppressed)
            return suppressed
        if record.attempts >= self._max_attempts or record.state is DeliveryState.EXHAUSTED:
            raise RetryBudgetExhausted(delivery_id)

        payload = self._payload(record)
        signature = "sha256=" + hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        attempt = replace(record, state=DeliveryState.DELIVERING, attempts=record.attempts + 1)
        await self._store.put(attempt)
        try:
            status = await self._transport.send(record.destination_ref, payload, signature)
            if not 200 <= status < 300:
                raise ConnectionError(f"webhook returned status {status}")
        except Exception as error:
            state = (
                DeliveryState.EXHAUSTED
                if attempt.attempts >= self._max_attempts
                else DeliveryState.PENDING
            )
            await self._store.put(replace(attempt, state=state, last_error=type(error).__name__))
            raise
        delivered = replace(attempt, state=DeliveryState.DELIVERED, response_status=status)
        await self._store.put(delivered)
        return delivered

    @staticmethod
    def delivery_key(context: ActionContext, permission: Permission) -> str:
        material = (
            f"{context.workspace_id}\0{context.event_id}\0{context.event_revision}\0"
            f"{permission.destination_ref}\0{permission.id}\0{permission.version}"
        ).encode()
        return "delivery-" + hashlib.sha256(material).hexdigest()

    def _payload(self, record: DeliveryRecord) -> bytes:
        payload = json.dumps(
            {
                "delivery_id": record.id,
                "event_id": record.event_id,
                "event_revision": record.event_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(payload) > self._max_payload_bytes:
            raise ValueError("webhook payload exceeds configured bound")
        return payload
