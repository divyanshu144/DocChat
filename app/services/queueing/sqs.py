from app.services.queueing import IngestMessage, MessageError, ReceivedMessage


class SQSQueue:
    """Standard SQS queue. Delivery is at-least-once, so consumers must be idempotent (see runner.claim_job)."""

    def __init__(self, queue_url: str, *, region: str | None = None, client=None):
        self.queue_url = queue_url
        self._region = region
        self._client_obj = client

    @property
    def _client(self):
        if self._client_obj is None:
            import boto3
            from botocore.config import Config
            self._client_obj = boto3.client(
                "sqs", region_name=self._region,
                config=Config(retries={"max_attempts": 5, "mode": "standard"},
                              connect_timeout=5, read_timeout=30),
            )
        return self._client_obj

    def send(self, message: IngestMessage) -> None:
        self._client.send_message(QueueUrl=self.queue_url, MessageBody=message.to_body())

    def receive(self, max_messages: int, wait_seconds: int) -> list[ReceivedMessage]:
        response = self._client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max(1, min(max_messages, 10)),
            WaitTimeSeconds=max(0, min(wait_seconds, 20)),
            AttributeNames=["ApproximateReceiveCount"],
        )
        received = []
        for raw in response.get("Messages", []):
            try:
                parsed = IngestMessage.from_body(raw.get("Body", ""))
            except MessageError:
                parsed = None
            count = int(raw.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            received.append(ReceivedMessage(raw["ReceiptHandle"], count, parsed))
        return received

    def delete(self, receipt: str) -> None:
        self._client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt)

    def change_visibility(self, receipt: str, seconds: int) -> None:
        self._client.change_message_visibility(
            QueueUrl=self.queue_url, ReceiptHandle=receipt,
            VisibilityTimeout=max(0, min(seconds, 43200)),
        )
