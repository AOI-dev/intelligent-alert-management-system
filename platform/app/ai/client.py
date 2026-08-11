"""Thin OpenAI-compatible chat client for the AI enrichment contour.

Talks to the vLLM server configured by VLLM_BASE_URL / VLLM_API_KEY /
VLLM_MODEL (platform/flags.env and the deployment host's private
platform/.env). Deliberately the only place in app/ that speaks HTTP to a
model: service.py owns prompts and parsing, tests swap this layer out, and
nothing else in the codebase grows a second way to call an LLM.

Every failure is raised as AIClientError; callers (the enrichment service)
turn that into a fallback EnrichmentResult rather than letting a model
outage reach the deterministic alert path.
"""
import json
import os

import httpx

VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "")
VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "")

DEFAULT_TIMEOUT_SECONDS = 30.0


class AIClientError(Exception):
    """The model endpoint was unreachable, misconfigured, or returned
    something unusable. Always safe to catch: it never means the platform
    itself is broken."""


def configured() -> bool:
    """True only when the contour has everything it needs to make a call.
    Model name is resolved per-request (see chat_json), so being unset at
    import time is not fatal."""
    return bool(VLLM_BASE_URL)


class LLMClient:
    """Async chat-completions caller. One instance per process; the httpx
    client is created lazily so importing this module never requires a
    running event loop or a live server."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = (base_url if base_url is not None else VLLM_BASE_URL).rstrip("/")
        self._api_key = api_key if api_key is not None else VLLM_API_KEY
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
            self._http = httpx.AsyncClient(
                base_url=self._base_url, headers=headers, timeout=self._timeout
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def default_model(self) -> str:
        """The model to serve when VLLM_MODEL is unset: whatever the server
        is actually running (vLLM serves exactly one). Fetched live so the
        contour follows a model swap on the server without a redeploy."""
        if VLLM_MODEL:
            return VLLM_MODEL
        try:
            resp = await (await self._client()).get("/models")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                raise AIClientError("vLLM /models returned no models")
            return data[0]["id"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise AIClientError(f"could not discover served model: {exc}") from exc

    async def chat_json(self, messages: list[dict], max_tokens: int = 512) -> tuple[dict, str]:
        """One chat completion constrained to a JSON object reply.

        Returns (parsed_json, model_id) — model_id is what the server says
        served the request, for EnrichmentResult.model_name/version. Raises
        AIClientError on transport failure, non-2xx, or a body that isn't
        valid JSON."""
        model = await self.default_model()
        try:
            resp = await (await self._client()).post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    # Bound the reply: enrichment output is one small JSON
                    # object, and an unbounded generation would stall every
                    # alert behind a runaway completion.
                    "max_tokens": max_tokens,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise AIClientError(f"chat completion failed: {exc}") from exc
        try:
            return json.loads(content), str(body.get("model", model))
        except ValueError as exc:
            raise AIClientError(f"model reply was not valid JSON: {exc}") from exc
