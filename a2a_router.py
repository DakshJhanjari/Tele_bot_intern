"""
a2a_router.py
~~~~~~~~~~~~~
FastAPI router that exposes the Google A2A (Agent-to-Agent) Protocol endpoints.

Endpoints:
  GET  /.well-known/agent.json  - Agent Card discovery
  POST /a2a                     - JSON-RPC 2.0 dispatcher

Supported JSON-RPC methods:
  tasks/send           - Synchronous task execution
  tasks/get            - Retrieve a stored task by ID
  tasks/sendSubscribe  - SSE streaming task execution
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from a2a_protocol import (
    AGENT_CARD,
    A2AHandler,
    JSONRPCRequest,
    JSONRPCResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_handler = A2AHandler()


# ---------------------------------------------------------------------------
# JSON-RPC error codes
# ---------------------------------------------------------------------------

_PARSE_ERROR       = {"code": -32700, "message": "Parse error"}
_INVALID_REQUEST   = {"code": -32600, "message": "Invalid Request"}
_METHOD_NOT_FOUND  = {"code": -32601, "message": "Method not found"}
_INVALID_PARAMS    = {"code": -32602, "message": "Invalid params"}
_INTERNAL_ERROR    = {"code": -32603, "message": "Internal error"}
_TASK_NOT_FOUND    = {"code": -32001, "message": "Task not found"}


# ---------------------------------------------------------------------------
# Agent Card endpoint
# ---------------------------------------------------------------------------

@router.get("/.well-known/agent.json", tags=["A2A"])
def agent_card():
    """
    Return the Agent Card so other agents can discover this agent's
    capabilities, skills, and API surface.
    """
    card = dict(AGENT_CARD)  # shallow copy to avoid mutating the global

    # Populate the URL dynamically from env vars set at deploy time
    base_url = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("BASE_URL")
        or ""
    )
    card["url"] = base_url.rstrip("/")

    return JSONResponse(content=card)


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------

@router.post("/a2a", tags=["A2A"])
async def a2a_endpoint(request_body: dict):
    """
    JSON-RPC 2.0 dispatcher for the A2A protocol.

    Dispatches to the correct handler based on the ``method`` field.
    Handles ``tasks/sendSubscribe`` via Server-Sent Events (SSE);
    all other methods return a standard JSON-RPC response.
    """
    rpc_id = request_body.get("id")

    # --- Basic validation ---
    if request_body.get("jsonrpc") != "2.0" or "method" not in request_body:
        return _error_response(rpc_id, _INVALID_REQUEST)

    method = request_body["method"]
    params = request_body.get("params", {})

    # --- Dispatch ---
    if method == "tasks/send":
        return await _handle_tasks_send(rpc_id, params)

    elif method == "tasks/get":
        return await _handle_tasks_get(rpc_id, params)

    elif method == "tasks/sendSubscribe":
        return _handle_tasks_send_subscribe(rpc_id, params)

    else:
        return _error_response(rpc_id, _METHOD_NOT_FOUND)


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------

async def _handle_tasks_send(rpc_id, params: dict):
    """Handle synchronous task execution."""
    try:
        task = _handler.handle_send(params)
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": task.model_dump(),
        })
    except ValueError as exc:
        logger.warning("[A2A] tasks/send invalid params: %s", exc)
        error = dict(_INVALID_PARAMS)
        error["data"] = str(exc)
        return _error_response(rpc_id, error)
    except Exception as exc:
        logger.exception("[A2A] tasks/send internal error: %s", exc)
        error = dict(_INTERNAL_ERROR)
        error["data"] = str(exc)
        return _error_response(rpc_id, error)


async def _handle_tasks_get(rpc_id, params: dict):
    """Handle task status retrieval."""
    try:
        task = _handler.handle_get(params)
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": task.model_dump(),
        })
    except ValueError as exc:
        error = dict(_INVALID_PARAMS)
        error["data"] = str(exc)
        return _error_response(rpc_id, error)
    except KeyError as exc:
        error = dict(_TASK_NOT_FOUND)
        error["data"] = str(exc)
        return _error_response(rpc_id, error)
    except Exception as exc:
        logger.exception("[A2A] tasks/get internal error: %s", exc)
        error = dict(_INTERNAL_ERROR)
        error["data"] = str(exc)
        return _error_response(rpc_id, error)


def _handle_tasks_send_subscribe(rpc_id, params: dict):
    """Handle streaming task execution via SSE."""
    def event_stream():
        try:
            for chunk in _handler.handle_send_subscribe(params):
                yield chunk
        except Exception as exc:
            import json
            logger.exception("[A2A] tasks/sendSubscribe error: %s", exc)
            # Send a final error event before closing
            error_payload = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {**_INTERNAL_ERROR, "data": str(exc)},
            }
            yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_response(rpc_id, error: dict) -> JSONResponse:
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": error,
    })
