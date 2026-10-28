"""Fixed-origin submission, with no provider/result/discovery implementation."""

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.external_summary import SubmissionAcknowledgement, SubmissionBody
from app.services.document_workflow_resume import digest_json

ORIGIN = "https://caring-doormat-pounce.ngrok-free.dev"
PATH = "/api/v2.1/project-summary"


class SubmissionFailure(Exception):
    def __init__(self, code: str, *, ambiguous: bool = True):
        self.code, self.ambiguous = code, ambiguous
        super().__init__(code)


@dataclass(frozen=True)
class SubmissionConfiguration:
    key: str = field(repr=False)
    connect_timeout: float
    total_timeout: float
    maximum_bytes: int

    @property
    def fingerprint(self) -> str:
        # Rotation does not change destination or pinned non-secret policy.
        return digest_json(
            [
                ORIGIN,
                PATH,
                self.connect_timeout,
                self.total_timeout,
                self.maximum_bytes,
                "submission-v1",
            ]
        )


def submission_configuration(settings: Settings) -> SubmissionConfiguration:
    key = settings.external_summary_api_key
    value = key.get_secret_value() if key else ""
    if (
        not settings.external_summary_enabled
        or settings.external_summary_base_url != ORIGIN
        or not 16 <= len(value) <= 512
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
    ):
        raise SubmissionFailure("EXTERNAL_SUMMARY_CONFIGURATION", ambiguous=False)
    return SubmissionConfiguration(
        value,
        settings.external_summary_connect_timeout_seconds,
        settings.external_summary_submit_timeout_seconds,
        settings.external_summary_max_response_bytes,
    )


async def submit_document(
    document_id: UUID,
    config: SubmissionConfiguration,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SubmissionAcknowledgement:
    try:
        async with asyncio.timeout(config.total_timeout):
            async with httpx.AsyncClient(
                verify=True,
                trust_env=False,
                follow_redirects=False,
                transport=transport,
                timeout=httpx.Timeout(config.total_timeout, connect=config.connect_timeout),
            ) as client:
                async with client.stream(
                    "POST",
                    ORIGIN + PATH,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "ngrok-skip-browser-warning": "true",
                        "X-API-Key": config.key,
                    },
                    json=SubmissionBody(document_id=document_id).model_dump(mode="json"),
                ) as response:
                    if response.status_code not in {200, 201, 202}:
                        # Even 4xx/5xx cannot establish whether remote work was created.
                        raise SubmissionFailure("EXTERNAL_SUMMARY_HTTP_REJECTED")
                    if (
                        response.headers.get("content-type", "").split(";")[0] != "application/json"
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        raise SubmissionFailure("EXTERNAL_SUMMARY_PROTOCOL")
                    data = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(data) + len(chunk) > config.maximum_bytes:
                            raise SubmissionFailure("EXTERNAL_SUMMARY_RESPONSE_LIMIT")
                        data.extend(chunk)
                    if config.key.encode() in data:
                        raise SubmissionFailure("EXTERNAL_SUMMARY_INVALID_ACK")
                    ack = SubmissionAcknowledgement.model_validate_json(bytes(data))
                    if ack.document_id != document_id or config.key in (ack.current_step or ""):
                        raise SubmissionFailure("EXTERNAL_SUMMARY_INVALID_ACK")
                    return ack
    except SubmissionFailure:
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        raise SubmissionFailure("EXTERNAL_SUMMARY_CONNECT", ambiguous=False) from None
    except (TimeoutError, httpx.HTTPError, ValidationError, ValueError):
        raise SubmissionFailure("EXTERNAL_SUMMARY_SUBMISSION_UNKNOWN") from None
