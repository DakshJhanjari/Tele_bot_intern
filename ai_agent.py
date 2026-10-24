import logging
import os
import time
import requests
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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

# Stable defaults with a configured primary model when provided.
FALLBACK_MODELS = list(dict.fromkeys(filter(None, [
    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
])))



def _get_client() -> genai.Client:
    """Return a cached Gemini client, initialising it on first call."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
        _client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=int(os.environ.get("GEMINI_REQUEST_TIMEOUT_MS", "20000"))))
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

_SYSTEM_PROMPT = """You write concise, personal internship outreach in the candidate's voice.
Candidate resume (the only source of candidate claims):
---
{resume}
---
Prioritize Founder's Office roles when a startup research profile is supplied.
Pitch a single role: Founder's Office internship. For an explicit job description,
honor that job's role instead. Do not combine PM, AI engineer, and Founder's Office titles.
Connect one specific, verifiable company fact to one relevant resume achievement.
Frame the fit around ownership, strategy and operations, customer research,
growth experiments, and taking work from idea to execution alongside founders.
Use product building or automation as evidence of execution, not as a second job pitch.
Only mention Grabit or its launch, responsibilities, stack, users, or orders if the resume
explicitly supports those exact claims. Never invent metrics, experience, company problems,
funding implications, or internal bottlenecks. Research fit suggestions are hypotheses,
not proof of a company's needs. If context is thin, use modest, factual language.
Write 80-120 words in three short paragraphs plus greeting and a signature using the
candidate's name from the resume. Address the supplied decision maker by first name,
or say 'Hi founding team' if unknown. Be warm, direct, and natural; avoid consultant
jargon, flattery about funding, lists of skills, generic compliments, and robotic hooks.
Make a practical, modest offer to contribute, and close with a low-friction question
about a Founder's Office internship or a short conversation. No invented availability.
Use a clear short subject, such as 'Founder’s Office internship at <company>'.
Extract the recipient only from an explicitly supplied decision-maker email address.
Never guess an address or use the candidate's own contact email. Leave it blank if absent.
Return the structured subject, body, and recruiter_email fields.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_email_draft(
    job_description_text: str = "", image_bytes: bytes | None = None
) -> DraftResponse:
    """Generate a tailored cold-email draft from a job description or startup profile.

    Uses configured/stable Flash models with bounded request timeouts and fallback.

    Args:
        job_description_text: Plain-text job description or startup research.
        image_bytes: Raw bytes of a job-description screenshot (optional).

    Returns:
        A :class:`DraftResponse` with subject, body, and recruiter email.
    """
    client = _get_client()
    resume_text = _get_resume()

    prompt = _SYSTEM_PROMPT.format(resume=resume_text)
    if job_description_text:
        prompt += f"\n\nJob Description / Company Profile provided:\n{job_description_text}"

    content: list = [prompt]
    if image_bytes:
        content.append(
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        )

    last_error: Exception | None = None

    for model_name in FALLBACK_MODELS:
        for attempt in range(2):
            try:
                logger.info("Attempting generation with model: %s (attempt %d/2)", model_name, attempt + 1)
                response = client.models.generate_content(
                    model=model_name,
                    contents=content,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DraftResponse,
                    ),
                )
                return DraftResponse.model_validate_json(response.text)
            except Exception as exc:
                last_error = exc
                err_str = str(exc)
                if any(x in err_str for x in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "high demand", "404", "NOT_FOUND")):
                    logger.warning(
                        "Model %s error (%s). Trying fallback...",
                        model_name,
                        err_str[:120],
                    )
                    time.sleep(1)
                    break  # Move immediately to next candidate model
                else:
                    logger.warning("Generation error on %s: %s", model_name, exc)
                    break

    raise last_error or RuntimeError("Failed to generate draft across all fallback models.")
