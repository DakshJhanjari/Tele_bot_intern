import os
import requests
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class DraftResponse(BaseModel):
    subject: str = Field(description="The subject line of the cold email")
    body: str = Field(description="The body content of the cold email")
    recruiter_email: str = Field(
        description="The extracted recruiter email, or an empty string if none found"
    )


# ---------------------------------------------------------------------------
# Module-level singletons  (created once, reused across all requests)
# ---------------------------------------------------------------------------

_client: genai.Client | None = None
_resume_cache: str | None = None


def _get_client() -> genai.Client:
    """Return a cached Gemini client, initialising it on first call."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
        _client = genai.Client(api_key=api_key)
    return _client


def _get_resume() -> str:
    """Return the resume text, fetching from the Gist only on first call."""
    global _resume_cache
    if _resume_cache is None:
        url = os.environ.get("RESUME_GIST_URL")
        if not url:
            raise ValueError("RESUME_GIST_URL is not set.")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        _resume_cache = response.text
    return _resume_cache


# ---------------------------------------------------------------------------
# Prompt template  (module-level constant — easy to iterate on)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an elite, highly persuasive cold email copywriter. Your goal is to \
write a cold email for the candidate that actually gets interviews.

Here is the candidate's resume:
---
{resume}
---

Your task is to analyze the provided job description and write a tailored, \
compelling cold email to the hiring manager/recruiter.

Rules for the email:
1. NO FLUFF. Do not use generic openings like "I hope this email finds you \
well," or "I am writing to apply for...". Start directly with a strong hook.
2. Keep it incredibly concise (under 150 words). Recruiters skim.
3. Focus purely on VALUE. Connect 1-2 specific achievements from the resume \
directly to the core needs in the job description.
4. Use bullet points if necessary to make it scannable.
5. End with a low-friction call to action (e.g., "Are you open to a brief \
chat next week?").
6. The tone must be confident, professional, and slightly conversational. \
Never sound desperate or robotic.
7. The subject line must be catchy, short, and highly relevant (e.g., \
avoiding generic "Application for [Role]").

If you can find an email address belonging to the recruiter or hiring manager \
in the text or image, extract it into the recruiter_email field. \
Otherwise, leave it blank.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_email_draft(
    job_description_text: str = "", image_bytes: bytes | None = None
) -> DraftResponse:
    """Generate a tailored cold-email draft from a job description.

    Args:
        job_description_text: Plain-text job description (may be empty if an
            image is provided instead).
        image_bytes: Raw bytes of a job-description screenshot (optional).

    Returns:
        A :class:`DraftResponse` with subject, body, and recruiter email.
    """
    client = _get_client()
    resume_text = _get_resume()

    prompt = _SYSTEM_PROMPT.format(resume=resume_text)
    if job_description_text:
        prompt += f"\n\nJob Description Text provided:\n{job_description_text}"

    content: list = [prompt]
    if image_bytes:
        content.append(
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=content,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DraftResponse,
        ),
    )

    return DraftResponse.model_validate_json(response.text)
