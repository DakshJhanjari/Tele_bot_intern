# Cold Email Drafter Agent & A2A Protocol Specification

> **Purpose**: This document provides a complete technical specification of the **Cold Email Drafter Agent** and its **Google Agent-to-Agent (A2A) Protocol interface**. It is designed to be easily ingested by another AI agent (such as an Antigravity prompt agent or LLM orchestrator) to discover, invoke, and handle tasks with this agent.

---

## 1. Agent Overview & Capabilities

* **Agent Name**: Cold Email Drafter / Intern Sorting Bot
* **Version**: `1.0.0`
* **Core Function**: Takes a job description (text or screenshot), extracts key details, matches them against the candidate's resume (`resume.txt`), crafts a personalized cold email (Subject + Body), automatically extracts the recruiter/HR email address if present, and saves it directly into the user's **Gmail Drafts**.
* **Base URL**: Configured via `BASE_URL` or `RENDER_EXTERNAL_URL` environment variables (e.g. `https://your-app.onrender.com` or `http://localhost:8000`).

### Core Internal Functions:
1. `generate_email_draft(job_description_text, image_bytes)`:
   - Uses Gemini AI (`gemini-2.5-flash` / `gemini-2.5-flash-lite`) with structured outputs (`Pydantic` schema).
   - Returns a `ColdEmailResponse` containing: `subject`, `body`, and `recruiter_email` (or `None`).
2. `create_draft(subject, body, to_email)`:
   - Interacts with Google Gmail API using OAuth credentials (`credentials.json` / `token.json`).
   - Inserts the generated email directly into Gmail Drafts.
3. **Telegram Bot Webhook**:
   - `POST /webhook` for direct human interaction via Telegram.

---

## 2. Google A2A (Agent-to-Agent) Protocol Overview

This agent implements the **Google A2A Protocol** over **JSON-RPC 2.0** over HTTP.

### Protocol Endpoints

| Endpoint | HTTP Method | Description |
|---|---|---|
| `/.well-known/agent.json` | `GET` | **Agent Card Discovery**: Returns metadata, skills, capabilities, and API endpoints. |
| `/a2a` | `POST` | **JSON-RPC 2.0 Dispatcher**: Primary entry point for executing agent tasks (`tasks/send`, `tasks/get`, `tasks/sendSubscribe`). |
| `/` | `GET` | Health check endpoint returning `{"status": "healthy"}`. |

---

## 3. Agent Card Specification (`GET /.well-known/agent.json`)

When an orchestrator agent sends a `GET` request to `/.well-known/agent.json`, it receives the Agent Card:

```json
{
  "name": "Cold Email Drafter",
  "description": "Generates tailored cold emails for job applications from a job description. Saves the draft directly to Gmail Drafts and returns a confirmation.",
  "url": "https://your-deployed-agent.com",
  "version": "1.0.0",
  "documentationUrl": "",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "skills": [
    {
      "id": "generate_cold_email",
      "name": "Generate Cold Email",
      "description": "Given a plain-text job description, generates a personalised cold email (subject line + body) using the candidate's resume, extracts the recruiter email if present, saves a Gmail Draft, and returns a confirmation artifact.",
      "tags": ["email", "cold-email", "job-application", "gmail"],
      "inputModes": ["text"],
      "outputModes": ["text"],
      "examples": [
        {
          "input": "Software Engineer at Acme Corp. Must have 3+ yrs Python...",
          "output": "Gmail draft saved. Subject: 'Python Engineer -> Acme Corp'"
        }
      ]
    }
  ]
}
```

---

## 4. JSON-RPC 2.0 Methods & Usage (`POST /a2a`)

All task requests must be sent as `POST` requests to `/a2a` with header `Content-Type: application/json`.

### Method 1: `tasks/send` (Synchronous Task Execution)
Use this method when you want to submit a job description and block until the email draft is saved to Gmail and the task completes.

#### Request Payload:
```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "tasks/send",
  "params": {
    "id": "task-uuid-optional",
    "sessionId": "session-uuid-optional",
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "Software Engineering Intern – Python Backend at Acme Corp. Contact: jobs@acmecorp.io. Requirements: Python, FastAPI, REST APIs."
        }
      ]
    }
  }
}
```

#### Successful Response Payload:
```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "id": "task-uuid-optional",
    "sessionId": "session-uuid-optional",
    "status": {
      "state": "completed",
      "message": null,
      "timestamp": null
    },
    "history": [
      {
        "role": "user",
        "parts": [
          {
            "type": "text",
            "text": "Software Engineering Intern..."
          }
        ]
      }
    ],
    "artifacts": [
      {
        "name": "email_draft_confirmation",
        "index": 0,
        "append": null,
        "lastChunk": null,
        "parts": [
          {
            "type": "text",
            "text": "Gmail draft saved successfully!\n\nTo: jobs@acmecorp.io\nSubject: Software Engineering Intern - Python Backend | Candidate Name\n\nCheck your Gmail Drafts folder to review and send."
          },
          {
            "type": "data",
            "data": {
              "subject": "Software Engineering Intern - Python Backend | Candidate Name",
              "body": "Dear Hiring Manager,\n\nI am writing to express my strong interest in...",
              "recruiter_email": "jobs@acmecorp.io",
              "gmail_draft_saved": true
            }
          }
        ]
      }
    ],
    "metadata": {}
  }
}
```

---

### Method 2: `tasks/sendSubscribe` (Streaming SSE Task Execution)
Use this method for real-time streaming progress updates over **Server-Sent Events (SSE)**.

#### Request Payload:
```json
{
  "jsonrpc": "2.0",
  "id": "sub-001",
  "method": "tasks/sendSubscribe",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "Full Stack Developer at TechCo..."
        }
      ]
    }
  }
}
```

#### SSE Stream Output Format:
Response Headers: `Content-Type: text/event-stream`

```text
event: task_status_update
data: {"id": "task-id", "status": {"state": "working"}}

event: task_artifact_update
data: {"id": "task-id", "artifact": {"name": "email_draft_confirmation", "parts": [...]}}

event: task_status_update
data: {"id": "task-id", "status": {"state": "completed"}}
```

---

### Method 3: `tasks/get` (Task Status Lookup)
Use this method to retrieve the stored status and artifacts of a task by its ID.

#### Request Payload:
```json
{
  "jsonrpc": "2.0",
  "id": "req-002",
  "method": "tasks/get",
  "params": {
    "id": "task-uuid-optional"
  }
}
```

---

## 5. JSON-RPC Error Codes

If an error occurs, the response contains an `error` object adhering to standard JSON-RPC 2.0:

| Code | Message | Description |
|---|---|---|
| `-32700` | `Parse error` | Invalid JSON syntax. |
| `-32600` | `Invalid Request` | Missing `jsonrpc: "2.0"` or `method`. |
| `-32601` | `Method not found` | Method is not `tasks/send`, `tasks/get`, or `tasks/sendSubscribe`. |
| `-32602` | `Invalid params` | Missing task ID or invalid parameters. |
| `-32603` | `Internal error` | Task execution failed (e.g. LLM failure, Gmail API error). |
| `-32001` | `Task not found` | Task ID not found in memory store. |

---

## 6. How Another Agent Should Invoke This Agent

If you are an AI agent or LLM orchestrator interacting with this agent:

1. **Discovery Step**: Send a `GET` request to `{BASE_URL}/.well-known/agent.json` to verify online status and confirm skill definitions.
2. **Task Execution**:
   - Construct a `tasks/send` JSON-RPC request.
   - Place the full target job posting text into `message.parts[0].text`.
   - Send `POST` to `{BASE_URL}/a2a`.
3. **Parse Artifact**:
   - Inspect `result.status.state`. Ensure it is `"completed"`.
   - Extract the artifact named `"email_draft_confirmation"`.
   - Read the structured `data` part for key values (`subject`, `body`, `recruiter_email`, `gmail_draft_saved`).
