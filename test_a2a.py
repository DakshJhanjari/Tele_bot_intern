"""
test_a2a.py
~~~~~~~~~~~
Quick manual smoke test for the A2A endpoints.

Usage (with the server running locally on port 8000):
    python test_a2a.py

Or against a deployed instance:
    python test_a2a.py --base-url https://your-deployed-url.com
"""

import argparse
import json
import uuid

import requests

DEFAULT_BASE_URL = "http://localhost:8000"

JOB_DESCRIPTION = """
Software Engineering Intern – Python Backend
Acme Corp | Remote | Summer 2025

We're looking for a motivated Python engineering intern to join our backend team.
You'll work on REST APIs, data pipelines, and ML integrations.

Requirements:
- Strong Python (FastAPI, Flask, or Django)
- Experience with async programming (asyncio)
- Familiarity with REST APIs and JSON
- Bonus: experience with LLMs or AI APIs

Contact: jobs@acmecorp.io
"""


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def test_agent_card(base_url: str):
    print_section("1. Agent Card Discovery")
    url = f"{base_url}/.well-known/agent.json"
    print(f"GET {url}")
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    card = resp.json()
    print(json.dumps(card, indent=2))
    assert card["name"] == "Cold Email Drafter", "Unexpected agent name"
    assert len(card["skills"]) > 0, "No skills in agent card"
    print("\n✅ Agent card OK")


def test_tasks_send(base_url: str) -> str:
    """Returns the task ID for use in test_tasks_get."""
    print_section("2. tasks/send (synchronous)")
    url = f"{base_url}/a2a"
    task_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": "test-send-1",
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [
                    {"type": "text", "text": JOB_DESCRIPTION}
                ],
            },
        },
    }
    print(f"POST {url}")
    print(f"Task ID: {task_id}")
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps(data, indent=2))
    assert "result" in data, f"Expected 'result', got: {data}"
    assert data["result"]["status"]["state"] == "completed", (
        f"Task not completed: {data['result']['status']}"
    )
    assert len(data["result"]["artifacts"]) > 0, "No artifacts returned"
    print("\n✅ tasks/send OK")
    return task_id


def test_tasks_get(base_url: str, task_id: str):
    print_section("3. tasks/get (retrieve stored task)")
    url = f"{base_url}/a2a"
    payload = {
        "jsonrpc": "2.0",
        "id": "test-get-1",
        "method": "tasks/get",
        "params": {"id": task_id},
    }
    print(f"POST {url}")
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps(data, indent=2))
    assert "result" in data, f"Expected 'result', got: {data}"
    assert data["result"]["id"] == task_id
    print("\n✅ tasks/get OK")


def test_tasks_send_subscribe(base_url: str):
    print_section("4. tasks/sendSubscribe (SSE streaming)")
    url = f"{base_url}/a2a"
    payload = {
        "jsonrpc": "2.0",
        "id": "test-sub-1",
        "method": "tasks/sendSubscribe",
        "params": {
            "id": str(uuid.uuid4()),
            "message": {
                "role": "user",
                "parts": [
                    {"type": "text", "text": JOB_DESCRIPTION}
                ],
            },
        },
    }
    print(f"POST {url} (streaming)")
    events = []
    with requests.post(url, json=payload, stream=True, timeout=90) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                print(decoded)
                if decoded.startswith("data:"):
                    events.append(json.loads(decoded[5:].strip()))
    assert len(events) > 0, "No SSE events received"
    print(f"\n✅ tasks/sendSubscribe OK — received {len(events)} events")


def test_method_not_found(base_url: str):
    print_section("5. Unknown method (error handling)")
    url = f"{base_url}/a2a"
    payload = {
        "jsonrpc": "2.0",
        "id": "test-err-1",
        "method": "tasks/nonexistent",
        "params": {},
    }
    resp = requests.post(url, json=payload, timeout=10)
    data = resp.json()
    print(json.dumps(data, indent=2))
    assert "error" in data
    assert data["error"]["code"] == -32601
    print("\n✅ Method not found error handling OK")


def main():
    parser = argparse.ArgumentParser(description="A2A protocol smoke tests")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"Base URL of the agent server (default: {DEFAULT_BASE_URL})"
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print(f"\nTesting A2A endpoints at: {base_url}")

    test_agent_card(base_url)
    task_id = test_tasks_send(base_url)
    test_tasks_get(base_url, task_id)
    test_tasks_send_subscribe(base_url)
    test_method_not_found(base_url)

    print("\n" + "=" * 60)
    print("  All A2A tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
