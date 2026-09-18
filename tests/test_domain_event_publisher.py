import logging
import unittest

from ai_node.runtime.domain_event_publisher import (
    MAXIMUM_DOMAIN_EVENT_PAYLOAD_BYTES,
    DomainEventPublisher,
    build_node_domain_event,
)


class _FakeAdapter:
    def __init__(self):
        self.calls = []

    async def publish_json(self, **kwargs):
        self.calls.append(kwargs)
        return True, None


def _trust_state():
    return {
        "node_id": "trusted-node-1",
        "operational_mqtt_host": "10.0.0.100",
        "operational_mqtt_port": 1883,
        "operational_mqtt_identity": "node:trusted-node-1",
        "operational_mqtt_token": "mqtt-token",
    }


class DomainEventPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishes_canonical_direct_event_contract(self):
        adapter = _FakeAdapter()
        publisher = DomainEventPublisher(
            logger=logging.getLogger("domain-event-test"),
            trust_state_provider=_trust_state,
            mqtt_adapter=adapter,
        )
        result = await publisher.publish(
            event_type="delivery.window.upserted",
            event_id="evt-123",
            component="email-parser",
            node_type="email-node",
            subject={"family": "delivery", "message_id": "msg-1"},
            data={"message_id": "msg-1", "sender_domain": "doordash.com"},
        )

        self.assertTrue(result["published"])
        call = adapter.calls[0]
        self.assertEqual(call["topic"], "hexe/events/delivery/window/upserted")
        self.assertEqual(call["payload"]["event_type"], "delivery.window.upserted")
        self.assertEqual(call["payload"]["source"]["node_id"], "trusted-node-1")
        self.assertEqual(call["qos"], 1)
        self.assertFalse(call["retain"])
        self.assertNotIn("promotion_id", call["payload"])
        self.assertNotIn("routing", call["payload"])

    async def test_rejects_private_raw_content_before_publish(self):
        adapter = _FakeAdapter()
        publisher = DomainEventPublisher(
            logger=logging.getLogger("domain-event-test"),
            trust_state_provider=_trust_state,
            mqtt_adapter=adapter,
        )
        with self.assertRaisesRegex(ValueError, "private raw-content field"):
            await publisher.publish(
                event_type="delivery.window.upserted",
                data={"raw_message": "private email text"},
            )
        self.assertEqual(adapter.calls, [])

    async def test_rejects_legacy_promotion_fields(self):
        publisher = DomainEventPublisher(
            logger=logging.getLogger("domain-event-test"),
            trust_state_provider=_trust_state,
            mqtt_adapter=_FakeAdapter(),
        )
        with self.assertRaisesRegex(ValueError, "legacy promotion field"):
            await publisher.publish(
                event_type="delivery.window.upserted",
                data={"routing": {"topic": "legacy"}},
            )

    def test_rejects_invalid_event_type_and_oversize_payload(self):
        with self.assertRaisesRegex(ValueError, "invalid_domain_event_type"):
            build_node_domain_event(trusted_node_id="node-1", event_type="Delivery/Updated")
        with self.assertRaisesRegex(ValueError, "domain_event_payload_too_large"):
            build_node_domain_event(
                trusted_node_id="node-1",
                event_type="delivery.window.upserted",
                data={"description": "x" * MAXIMUM_DOMAIN_EVENT_PAYLOAD_BYTES},
            )

    async def test_requires_trusted_operational_identity(self):
        adapter = _FakeAdapter()
        publisher = DomainEventPublisher(
            logger=logging.getLogger("domain-event-test"),
            trust_state_provider=lambda: {},
            mqtt_adapter=adapter,
        )
        result = await publisher.publish(event_type="delivery.window.upserted")
        self.assertFalse(result["published"])
        self.assertEqual(result["last_error"], "invalid_operational_mqtt_credentials")
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
