"""Real OpenAI-compatible provider adapter.

Converts provider-neutral AIRequest to the OpenAI-style HTTP payload, calls
the provider over async httpx, normalizes the response, and maps HTTP errors
to provider-neutral exceptions. No API keys or raw responses escape.
"""

import json
from typing import AsyncGenerator

import httpx

from app.ai.contracts import AIRequest, AIResponse, AIToolCall, AIUsage
from app.ai.exceptions import (
    AIAuthenticationError,
    AIInvalidRequestError,
    AIModelNotFoundError,
    AIProviderError,
    AIProviderUnavailableError,
    AIRateLimitError,
)
from app.ai.metadata import ProviderMetadata
from app.ai.providers.base import OpenAICompatibleProvider
from app.ai.streaming import AIStreamEvent, AIStreamEventType


class OpenAICompatibleHTTPProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        metadata: ProviderMetadata,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(metadata)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Injectable client for tests; otherwise a client with explicit timeout.
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def generate(
        self, request: AIRequest, credential_override: str | None = None
    ) -> AIResponse:
        payload = self._build_payload(request)
        headers = {
            "Authorization": f"Bearer {credential_override or self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderUnavailableError("provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise AIProviderUnavailableError("provider request failed") from exc

        self._raise_for_status(response)
        return self._parse_response(request, response)

    def stream(
        self, request: AIRequest, credential_override: str | None = None
    ) -> AsyncGenerator[AIStreamEvent, None]:
        payload = self._build_payload(request)
        payload["stream"] = True
        headers = {
            "Authorization": f"Bearer {credential_override or self._api_key}",
            "Content-Type": "application/json",
        }

        async def _gen() -> AsyncGenerator[AIStreamEvent, None]:
            yield AIStreamEvent(
                type=AIStreamEventType.START,
                data={"provider_id": request.provider_id, "model_id": request.model_id},
            )
            finish_reason = "stop"
            usage = {"input_tokens": 0, "output_tokens": 0}
            try:
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError as exc:
                            raise AIProviderError("malformed provider stream") from exc
                        try:
                            choice = data["choices"][0]
                            delta = choice.get("delta", {}) or {}
                            content = delta.get("content")
                            if content:
                                yield AIStreamEvent(type=AIStreamEventType.TOKEN, data={"delta": content})
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
                            if data.get("usage"):
                                usage = {
                                    "input_tokens": int(data["usage"].get("prompt_tokens") or 0),
                                    "output_tokens": int(data["usage"].get("completion_tokens") or 0),
                                }
                        except (KeyError, IndexError, TypeError) as exc:
                            raise AIProviderError("malformed provider stream") from exc
            except httpx.TimeoutException as exc:
                raise AIProviderUnavailableError("provider request timed out") from exc
            except httpx.HTTPError as exc:
                raise AIProviderUnavailableError("provider request failed") from exc

            yield AIStreamEvent(
                type=AIStreamEventType.END,
                data={"finish_reason": finish_reason, "usage": usage},
            )

        return _gen()

    @staticmethod
    def _build_payload(request: AIRequest) -> dict:
        messages: list[dict] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        for message in request.messages:
            messages.append({"role": message.role.value, "content": message.content})

        payload: dict = {"model": request.model_id, "messages": messages}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "chatbot_response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        if request.tools is not None:
            built_tools = []
            for tool in request.tools:
                if not isinstance(tool, dict) or "name" not in tool or "parameters" not in tool:
                    raise AIInvalidRequestError(
                        "each tool definition requires 'name' and 'parameters'"
                    )
                built_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool["parameters"],
                        },
                    }
                )
            payload["tools"] = built_tools
        # metadata is intentionally not sent to the provider.
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        status = response.status_code
        if status == 400:
            raise AIInvalidRequestError("provider rejected the request")
        if status in (401, 403):
            raise AIAuthenticationError("provider authentication failed")
        if status == 404:
            raise AIModelNotFoundError("provider model not found")
        if status == 429:
            raise AIRateLimitError("provider rate limit exceeded")
        if status in (408, 502, 503, 504):
            raise AIProviderUnavailableError("provider unavailable")
        raise AIProviderError(f"provider error (status {status})")

    @staticmethod
    def _parse_response(request: AIRequest, response: httpx.Response) -> AIResponse:
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AIProviderError("malformed provider response") from exc

        try:
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content") or ""
            finish_reason = choice.get("finish_reason") or "stop"
            raw_tool_calls = message.get("tool_calls")
            tool_calls = (
                [
                    AIToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    )
                    for tc in raw_tool_calls
                ]
                if raw_tool_calls
                else None
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("malformed provider response") from exc

        usage_data = data.get("usage") or {}
        usage = AIUsage(
            input_tokens=int(usage_data.get("prompt_tokens") or 0),
            output_tokens=int(usage_data.get("completion_tokens") or 0),
        )

        return AIResponse(
            content=content,
            provider_id=request.provider_id,
            model_id=request.model_id,
            finish_reason=finish_reason,
            usage=usage,
            metadata={},
            tool_calls=tool_calls,
        )
