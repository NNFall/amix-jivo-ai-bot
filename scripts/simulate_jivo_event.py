import json
from argparse import ArgumentParser
from urllib import request


def main() -> None:
    parser = ArgumentParser(description="Send a test Jivo webhook payload to the local service.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/jivo/change-me")
    parser.add_argument("--text", default="Есть артикул AB-123?")
    parser.add_argument("--event-id", default="local-test-event-1")
    parser.add_argument("--chat-id", default="local-chat-1")
    parser.add_argument("--client-id", default="local-client-1")
    args = parser.parse_args()

    payload = {
        "id": args.event_id,
        "event": "CLIENT_MESSAGE",
        "chat_id": args.chat_id,
        "client_id": args.client_id,
        "sender": {"id": "site-user", "name": "Local Tester"},
        "message": {"type": "TEXT", "text": args.text},
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=args.url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=10) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
