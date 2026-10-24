"""
a2a_protocol.py
~~~~~~~~~~~~~~~
Google A2A (Agent-to-Agent) Protocol — data models and task handler.

This module contains:
  - All Pydantic models that mirror the A2A spec types.
  - A2AHandler: receives a Task, runs the agent logic, and returns an
    updated Task with status and artifacts.

Spec reference: https://google.github.io/A2A/
"""

from __future__ import annotations

import json
import logging
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ai_agent import generate_email_draft
from gmail_integration import create_draft

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# A2A Core Types
# ---------------------------------------------------------------------------

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"


class TextPart(BaseModel):
    """A plain-text content part."""
    type: Literal["text"] = "text"
    text: str


class DataPart(BaseModel):
    """A structured data content part (JSON dict)."""
    type: Literal["data"] = "data"
    data: dict[str, Any]


# Union alias - discriminated by the `type` field
Part = TextPart | DataPart


class Message(BaseModel):
    """A single message in a task conversation turn."""
    role: Literal["user", "agent"]
    parts: list[Part]


class Artifact(BaseModel):
    """An output artifact produced by the agent."""
    name: str
    parts: list[Part]
    index: int = 0
    append: bool | None = None
    lastChunk: bool | None = None


class TaskStatus(BaseModel):
    """Current execution status of a task."""
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None


class Task(BaseModel):
    """Top-level A2A Task object."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str | None = None
    status: TaskStatus = Field(
        default_factory=lambda: TaskStatus(state=TaskState.SUBMITTED)
    )
    history: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 Envelope Types
# ---------------------------------------------------------------------------

class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any = None
    error: dict[str, Any] | None = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any | None = None


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

AGENT_CARD: dict[str, Any] = {
    "name": "Cold Email Drafter",
    "description": (
        "Generates tailored cold emails for job applications from a job description. "
        "Saves the draft directly to Gmail Drafts and returns a confirmation."
    ),
    "url": "",           # Filled at startup from RENDER_EXTERNAL_URL or BASE_URL env var
    "version": "1.0.0",
    "documentationUrl": "",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [
        {
            "id": "generate_cold_email",
            "name": "Generate Cold Email",
            "description": (
                "Given a plain-text job description, generates a personalised cold email "
                "(subject line + body) using the candidate's resume, extracts the recruiter "
                "email if present, saves a Gmail Draft, and returns a confirmation artifact."
            ),
            "tags": ["email", "cold-email", "job-application", "gmail"],
            "inputModes": ["text"],
            "outputModes": ["text"],
            "examples": [
                {
                    "input": "Software Engineer at Acme Corp. Must have 3+ yrs Python...",
                    "output": "Gmail draft saved. Subject: 'Python Engineer -> Acme Corp'",
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# In-memory task store  (single-process; replace with Redis for multi-worker)
# ---------------------------------------------------------------------------

_TASK_STORE: dict[str, Task] = {}


def get_task(task_id: str) -> Task | None:
    return _TASK_STORE.get(task_id)


def save_task(task: Task) -> None:
    _TASK_STORE[task.id] = task


# ---------------------------------------------------------------------------
# A2A Task Handler
# ---------------------------------------------------------------------------

class A2AHandler:
    """Processes A2A tasks for this agent."""

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def handle_send(self, params: dict[str, Any]) -> Task:
        """Handle a synchronous ``tasks/send`` request."""
        task = self._init_task(params)
        save_task(task)
        self._execute(task, save_draft=params.get("save_draft", True) is not False)
        save_task(task)
        return task

    def handle_get(self, params: dict[str, Any]) -> Task:
        """Handle a ``tasks/get`` request."""
        task_id = params.get("id")
        if not task_id:
            raise ValueError("Missing task id")
        task = get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")
        return task

    def handle_send_subscribe(self, params: dict[str, Any]):
        """
        Generator for ``tasks/sendSubscribe`` (SSE streaming).
        Yields SSE-formatted strings as the task progresses.
        """
        task = self._init_task(params)
        save_task(task)

        # Yield "working" status
        task.status = TaskStatus(state=TaskState.WORKING)
        save_task(task)
        yield self._sse_event("task_status_update", task)

        # Execute the actual work
        self._execute(task)
        save_task(task)

        # Yield each artifact
        for artifact in task.artifacts:
            yield self._sse_event("task_artifact_update", {
                "id": task.id,
                "artifact": artifact.model_dump(),
            })

        # Yield final status
        yield self._sse_event("task_status_update", task)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_task(self, params: dict[str, Any]) -> Task:
        """Build a Task from JSON-RPC params."""
        task_id = params.get("id") or str(uuid.uuid4())
        session_id = params.get("sessionId")

        raw_message = params.get("message", {})
        role = raw_message.get("role", "user")
        raw_parts = raw_message.get("parts", [])
        parts: list[Part] = []
        for p in raw_parts:
            if p.get("type") == "text":
                parts.append(TextPart(text=p.get("text", "")))
            elif p.get("type") == "data":
                parts.append(DataPart(data=p.get("data", {})))

        message = Message(role=role, parts=parts)

        task = Task(
            id=task_id,
            sessionId=session_id,
            status=TaskStatus(state=TaskState.SUBMITTED),
            history=[message],
        )
        return task

    def _execute(self, task: Task, save_draft: bool = True) -> None:
        """
        Run the agent logic and update the task in-place.
        Saves the email draft to Gmail and stores a confirmation artifact.
        """
        task.status = TaskStatus(state=TaskState.WORKING)

        # Extract text from the last user message
        job_text = ""
        for msg in reversed(task.history):
            if msg.role == "user":
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        job_text += part.text + "\n"
                break

        job_text = job_text.strip()
        if not job_text:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text="No job description text was provided.")],
                ),
            )
            return

        try:
            logger.info("[A2A] Generating email draft for task %s", task.id)
            draft = generate_email_draft(job_description_text=job_text)

            if save_draft:
                create_draft(subject=draft.subject, body=draft.body, to_email=draft.recruiter_email)

            to_display = draft.recruiter_email or "[Blank]"
            confirmation_text = (
                "Gmail draft saved successfully!\n\n"
                f"To: {to_display}\n"
                f"Subject: {draft.subject}\n\n"
                "Check your Gmail Drafts folder to review and send."
            )

            task.status = TaskStatus(state=TaskState.COMPLETED)
            task.artifacts = [
                Artifact(
                    name="email_draft_confirmation",
                    parts=[
                        TextPart(text=confirmation_text if save_draft else "Email preview ready. Nothing has been saved or sent."),
                        DataPart(data={
                            "subject": draft.subject,
                            "body": draft.body,
                            "recruiter_email": draft.recruiter_email,
                            "gmail_draft_saved": save_draft,
                        }),
                    ],
                )
            ]

        except Exception as exc:
            logger.exception("[A2A] Task %s failed: %s", task.id, exc)
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=f"Error: {exc}")],
                ),
            )

    @staticmethod
    def _sse_event(event: str, data: Any) -> str:
        """Format a Server-Sent Events message."""
        if isinstance(data, Task):
            payload = data.model_dump()
        else:
            payload = data
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"
