"""Google Gemini implementation of the LLM provider interface."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import google.generativeai as genai

from ..base import LLMProvider, LLMResult
from ..gemini_key_manager import GeminiKeyManager, GeminiKeyExhaustedError

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Adapter for Google's Gemini API with multi-key rotation support."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        default_model: str,
        key_manager: GeminiKeyManager | None = None,
    ) -> None:
        self._fallback_key = api_key
        self._key_manager = key_manager
        self.default_model = default_model

        # Only configure globally when there's no key manager
        if not key_manager:
            genai.configure(api_key=api_key)

        # Cache per (api_key, model_name) to avoid recreating
        self._models_cache: dict[tuple[str, str], genai.GenerativeModel] = {}

    def _get_model(self, model_name: str, api_key: str | None = None) -> genai.GenerativeModel:
        """Get or create a GenerativeModel instance for the given key+model."""
        cache_key = (api_key or self._fallback_key, model_name)
        if cache_key not in self._models_cache:
            # Reconfigure genai for this key before creating the model
            genai.configure(api_key=cache_key[0])
            self._models_cache[cache_key] = genai.GenerativeModel(model_name)
        return self._models_cache[cache_key]

    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult:
        config = config or {}
        model_name = config.get("model") or self.default_model

        if self._key_manager:
            return await self._chat_with_rotation(messages, config, model_name)
        return await self._do_chat(messages, config, model_name, self._fallback_key)

    async def _chat_with_rotation(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any],
        model_name: str,
    ) -> LLMResult:
        """Try the request with key rotation on quota errors."""
        max_retries = len(self._key_manager._keys)  # noqa: SLF001
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                api_key = self._key_manager.get_key(model_name)  # type: ignore[union-attr]
            except GeminiKeyExhaustedError:
                raise last_error or GeminiKeyExhaustedError(
                    f"All Gemini keys exhausted for model '{model_name}'."
                )

            try:
                result = await self._do_chat(messages, config, model_name, api_key)
                # Success — record usage
                self._key_manager.record_usage(api_key, model_name)  # type: ignore[union-attr]
                return result
            except Exception as exc:
                err_str = str(exc).lower()
                is_quota_error = any(
                    kw in err_str
                    for kw in ("429", "resource_exhausted", "quota", "rate limit")
                )
                if is_quota_error:
                    logger.warning(
                        "Key quota hit for model=%s (attempt %d/%d): %s",
                        model_name,
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    self._key_manager.mark_exhausted(api_key, model_name)  # type: ignore[union-attr]
                    last_error = exc
                    continue
                # Non-quota error — don't retry
                raise

        raise last_error or GeminiKeyExhaustedError(
            f"All Gemini keys exhausted for model '{model_name}'."
        )

    async def _do_chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any],
        model_name: str,
        api_key: str,
    ) -> LLMResult:
        """Execute a single chat request against the Gemini API."""
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 500)
        tools = config.get("tools")

        logger.debug(
            "Gemini chat request model=%s temperature=%s max_tokens=%s tools=%s",
            model_name,
            temperature,
            max_tokens,
            len(tools) if tools else 0,
        )

        # Reconfigure for this key and get model
        genai.configure(api_key=api_key)
        model = self._get_model(model_name, api_key)

        # Convert OpenAI-style messages to Gemini format
        gemini_messages = self._convert_messages(messages)

        # Convert tools to Gemini format if provided
        gemini_tools = None
        if tools:
            gemini_tools = self._convert_tools_to_gemini(tools)

        # Configure generation parameters
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            top_p=config.get("top_p", 1.0),
        )

        try:
            if len(gemini_messages) == 1 and "content" in gemini_messages[0]:
                response = await model.generate_content_async(
                    gemini_messages[0]["content"],
                    generation_config=generation_config,
                    tools=gemini_tools,
                )
            else:
                chat = model.start_chat(history=gemini_messages[:-1])
                last_message = gemini_messages[-1]

                if "content" in last_message:
                    response = await chat.send_message_async(
                        last_message["content"],
                        generation_config=generation_config,
                        tools=gemini_tools,
                    )
                else:
                    response = await chat.send_message_async(
                        last_message["parts"],
                        generation_config=generation_config,
                        tools=gemini_tools,
                    )

            # Extract function calls if present
            tool_calls = None
            content = ""
            if response.candidates and response.candidates[0].content.parts:
                function_calls = []
                text_parts = []

                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        function_calls.append({
                            "id": f"call_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {
                                "name": fc.name,
                                "arguments": dict(fc.args) if fc.args else {},
                            },
                        })
                    elif hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)

                if function_calls:
                    tool_calls = function_calls
                content = "".join(text_parts)

            finish_reason = response.candidates[0].finish_reason.name if response.candidates else "UNKNOWN"

            usage_dict = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_dict = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count,
                }

            metadata = {
                "finish_reason": finish_reason,
                "model": model_name,
                "api_key_masked": api_key[:8] + "..." + api_key[-4:],
            }

            return LLMResult(
                provider=self.name,
                model=model_name,
                content=content,
                finish_reason=finish_reason,
                usage=usage_dict,
                raw_response_id=None,
                metadata=metadata,
                tool_calls=tool_calls,
            )

        except Exception as e:
            logger.error("Gemini API call failed: %s", e, exc_info=True)
            raise

    def _convert_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """
        Convert OpenAI-style messages to Gemini format.

        OpenAI format: [{"role": "system|user|assistant|tool", "content": "..."}]
        Gemini format: [{"role": "user|model", "parts": ["..."|FunctionResponse]}]
        """
        from google.ai.generativelanguage_v1beta.types import FunctionResponse, Part

        gemini_messages = []
        system_content = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_content = content
                continue

            if role == "tool":
                tool_name = msg.get("name", "")
                func_response = FunctionResponse(
                    name=tool_name,
                    response={"result": content}
                )
                gemini_messages.append({
                    "role": "user",
                    "parts": [Part(function_response=func_response)],
                })
                continue

            gemini_role = "model" if role == "assistant" else "user"

            if system_content and gemini_role == "user" and not gemini_messages:
                content = f"{system_content}\n\n{content}"
                system_content = None

            gemini_messages.append({
                "role": gemini_role,
                "parts": [content] if isinstance(content, str) else content,
            })

        if len(gemini_messages) == 1:
            parts = gemini_messages[0].get("parts", [])
            if parts and isinstance(parts[0], str):
                return [{"content": parts[0]}]

        return gemini_messages

    def _convert_tools_to_gemini(self, openai_tools: list[dict[str, Any]]) -> list[Any]:
        """Convert OpenAI-format tools to Gemini function declarations."""
        from google.ai.generativelanguage_v1beta.types import FunctionDeclaration, Schema, Type

        function_declarations = []

        for tool in openai_tools:
            if tool.get("type") != "function":
                continue

            func_def = tool.get("function", {})
            name = func_def.get("name")
            description = func_def.get("description", "")
            parameters = func_def.get("parameters", {})

            gemini_params = self._convert_schema_to_gemini(parameters)

            func_decl = FunctionDeclaration(
                name=name,
                description=description,
                parameters=gemini_params,
            )
            function_declarations.append(func_decl)

        if function_declarations:
            from google.ai.generativelanguage_v1beta.types import Tool
            return [Tool(function_declarations=function_declarations)]

        return None

    def _convert_schema_to_gemini(self, openai_schema: dict[str, Any]) -> "Schema":
        """Convert OpenAI JSON schema to Gemini Schema."""
        from google.ai.generativelanguage_v1beta.types import Schema, Type

        type_mapping = {
            "string": Type.STRING,
            "number": Type.NUMBER,
            "integer": Type.INTEGER,
            "boolean": Type.BOOLEAN,
            "object": Type.OBJECT,
            "array": Type.ARRAY,
        }

        schema_type = openai_schema.get("type", "object")
        gemini_type = type_mapping.get(schema_type, Type.STRING)

        schema_kwargs = {"type": gemini_type}

        if schema_type == "object" and "properties" in openai_schema:
            properties = {}
            for prop_name, prop_schema in openai_schema["properties"].items():
                properties[prop_name] = self._convert_schema_to_gemini(prop_schema)
            schema_kwargs["properties"] = properties

        if "required" in openai_schema:
            schema_kwargs["required"] = openai_schema["required"]

        if "description" in openai_schema:
            schema_kwargs["description"] = openai_schema["description"]

        if "enum" in openai_schema:
            schema_kwargs["enum"] = openai_schema["enum"]

        if schema_type == "array" and "items" in openai_schema:
            schema_kwargs["items"] = self._convert_schema_to_gemini(openai_schema["items"])

        return Schema(**schema_kwargs)
