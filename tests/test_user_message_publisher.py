import json
import logging
import unittest
from unittest.mock import patch

from ai_node.runtime.user_message_publisher import USER_MESSAGE_TOPIC, UserMessagePublisher


class UserMessagePublisherTests(unittest.TestCase):
    def test_publishes_qos_one_non_retained_event(self):
        class _PublishInfo:
            rc = 0

            def wait_for_publish(self, timeout):
                self.timeout = timeout

            def is_published(self):
                return True

        class _Client:
            def __init__(self):
                self.info = _PublishInfo()

            def username_pw_set(self, identity, token):
                self.credentials = (identity, token)

            def connect(self, host, port, keepalive):
                self.connection = (host, port, keepalive)

            def loop_start(self):
                pass

            def publish(self, topic, payload, qos, retain):
                self.published = (topic, json.loads(payload), qos, retain)
                return self.info

            def loop_stop(self):
                pass

            def disconnect(self):
                pass

        client = _Client()
        with patch("ai_node.runtime.user_message_publisher.mqtt.Client", return_value=client):
            published, error = UserMessagePublisher(logger=logging.getLogger("test")).publish(
                trust_state={
                    "operational_mqtt_host": "mqtt.test",
                    "operational_mqtt_port": 1883,
                    "operational_mqtt_identity": "node-test",
                    "operational_mqtt_token": "secret",
                },
                payload={"event_type": "user.message"},
            )

        self.assertTrue(published)
        self.assertIsNone(error)
        self.assertEqual(client.published, (USER_MESSAGE_TOPIC, {"event_type": "user.message"}, 1, False))


if __name__ == "__main__":
    unittest.main()
