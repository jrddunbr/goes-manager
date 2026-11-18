"""RabbitMQ queue helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import time
from urllib.parse import urlsplit
from typing import Callable

logger = logging.getLogger(__name__)

PRIMARY_QUEUE_NAMES = [
    "ingest-jobs",
    "decode-jobs",
    "materialize-jobs",
    "derivative-jobs",
    "retention-jobs",
    "reconcile-jobs",
    "replay-jobs",
]

PRIMARY_QUEUE_ARGUMENTS = {
    "x-dead-letter-exchange": "dead-letter",
    "x-dead-letter-routing-key": "dead-letter",
}

QUEUE_NAMES = {
    "ingest-watcher": "ingest-jobs",
    "ingest-uploader": "ingest-jobs",
    "decoder-worker": "decode-jobs",
    "materializer-worker": "materialize-jobs",
    "retention-controller": "retention-jobs",
    "metadata-retention-controller": "retention-jobs",
    "reconciler": "reconcile-jobs",
    "backfill-runner": "replay-jobs",
    "observability-agent": "reconcile-jobs",
    "alerts-worker": "derivative-jobs",
    "timelapse-worker": "derivative-jobs",
    "analysis-worker": "derivative-jobs",
}


@dataclass(frozen=True)
class JobEnvelope:
    job_id: str
    job_type: str
    trace_id: str
    attempt: int
    payload: dict[str, object]
    created_at: str = ""

    def as_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "job_type": self.job_type,
                "trace_id": self.trace_id,
                "attempt": self.attempt,
                "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
                "payload": self.payload,
            }
        )


class RabbitQueueClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self._publisher_connection = None
        self._publisher_channel = None
        self._declared_publish_queues: set[str] = set()

    def _connect(self):
        import pika

        deadline = time.monotonic() + 90
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                parameters = pika.URLParameters(self.url)
                # Callbacks can upload large files on a Pi; do not starve heartbeats.
                parameters.heartbeat = 0
                parameters.blocked_connection_timeout = 60
                parameters.socket_timeout = 10
                return pika.BlockingConnection(parameters)
            except pika.exceptions.AMQPConnectionError as exc:
                last_error = exc
                logger.info("Waiting for RabbitMQ on %s", urlsplit(self.url).hostname)
                time.sleep(2)
        if last_error is not None:
            raise last_error
        return pika.BlockingConnection(pika.URLParameters(self.url))

    def declare_standard_queues(self) -> None:
        import pika

        connection = self._connect()
        try:
            channel = connection.channel()
            channel.exchange_declare(exchange="dead-letter", exchange_type="direct", durable=True)
            channel.exchange_declare(exchange="retry", exchange_type="direct", durable=True)
            channel.queue_declare(queue="dead-letter", durable=True)
            channel.queue_bind(queue="dead-letter", exchange="dead-letter", routing_key="dead-letter")
            for queue_name in PRIMARY_QUEUE_NAMES:
                channel.queue_declare(
                    queue=queue_name,
                    durable=True,
                    arguments=PRIMARY_QUEUE_ARGUMENTS,
                )
                retry_queue = f"{queue_name}.retry"
                channel.queue_declare(
                    queue=retry_queue,
                    durable=True,
                    arguments={
                        "x-message-ttl": 15000,
                        "x-dead-letter-exchange": "",
                        "x-dead-letter-routing-key": queue_name,
                    },
                )
                channel.queue_bind(queue=retry_queue, exchange="retry", routing_key=queue_name)
        finally:
            connection.close()

    def publish(self, queue_name: str, envelope: JobEnvelope) -> None:
        import pika

        channel = self._publisher()
        if queue_name not in self._declared_publish_queues:
            channel.queue_declare(queue=queue_name, durable=True, arguments=PRIMARY_QUEUE_ARGUMENTS)
            self._declared_publish_queues.add(queue_name)
        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            body=envelope.as_json(),
            properties=pika.BasicProperties(delivery_mode=2),
            mandatory=True,
        )
        logger.debug("Published job %s to %s", envelope.job_id, queue_name)

    def _publisher(self):
        connection = self._publisher_connection
        channel = self._publisher_channel
        if connection is not None and channel is not None and connection.is_open and channel.is_open:
            return channel
        self._publisher_connection = self._connect()
        self._publisher_channel = self._publisher_connection.channel()
        self._publisher_channel.confirm_delivery()
        self._declared_publish_queues.clear()
        return self._publisher_channel

    def close(self) -> None:
        connection = self._publisher_connection
        if connection is not None and connection.is_open:
            connection.close()
        self._publisher_connection = None
        self._publisher_channel = None
        self._declared_publish_queues.clear()

    def consume_forever(self, queue_name: str, handler: Callable[[dict[str, object]], None]) -> None:
        import pika

        connection = self._connect()
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True, arguments=PRIMARY_QUEUE_ARGUMENTS)
        channel.basic_qos(prefetch_count=1)
        channel.confirm_delivery()

        def _callback(ch, method, properties, body):
            try:
                envelope = decode_message(body)
                handler_payload = payload_from_envelope(envelope)
                attempt = int(envelope.get("attempt", 1))
            except (ValueError, TypeError, UnicodeError):
                logger.exception("Invalid message in %s", queue_name)
                ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
                return
            try:
                handler(handler_payload)
            except Exception as exc:
                logger.exception("Worker failed while handling message from %s", queue_name)
                envelope.update(attempt=attempt + 1, last_error=str(exc)[:2000],
                                failed_at=datetime.now(timezone.utc).isoformat(), worker=queue_name)
                terminal = attempt >= 8
                # Acknowledge the original only after RabbitMQ confirms its replacement.
                ch.basic_publish(
                    exchange="dead-letter" if terminal else "retry",
                    routing_key="dead-letter" if terminal else queue_name,
                    body=json.dumps(envelope),
                    properties=pika.BasicProperties(delivery_mode=2),
                    mandatory=True,
                )
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=queue_name, on_message_callback=_callback)
        logger.info("Consuming queue %s", queue_name)
        try:
            channel.start_consuming()
        finally:
            if connection.is_open:
                connection.close()


def queue_name_for_role(role: str) -> str | None:
    return QUEUE_NAMES.get(role)


def decode_message(body: bytes) -> dict[str, object]:
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Queue message must decode to a JSON object")
    return payload


def payload_from_envelope(envelope: dict[str, object]) -> dict[str, object]:
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        return payload
    return envelope
