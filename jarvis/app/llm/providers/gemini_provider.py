"""Google Gemini implementation of the LLM provider interface."""
from __future__ import annotations

import logging
from typing import Any

import google.generativeai as genai

from ..base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Adapter for Google's Gemini API."""

    name = "gemini"

    def __init__(self, api_key: str, default_model: str) -> None:
        genai.configure(api_key=api_key)
        self.default_model = default_model
        self._models_cache: dict[str, genai.GenerativeModel] = {}

    def _get_model(self, model_name: str) -> genai.GenerativeModel:
        """Get or create a GenerativeModel instance."""
        if model_name not in self._models_cache:
            self._models_cache[model_name] = genai.GenerativeModel(model_name)
        return self._models_cache[model_name]

    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult:
        config = config or {}
        model_name = config.get("model") or self.default_model
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 500)
        tools = config.get("tools")  # OpenAI-format tools

        logger.debug(
            "Gemini chat request model=%s temperature=%s max_tokens=%s tools=%s",
            model_name,
            temperature,
            max_tokens,
            len(tools) if tools else 0,
        )

        # Get model instance
        model = self._get_model(model_name)

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
            # For Gemini, we need to handle the conversation differently
            # If there's only a system message and user message, use generate_content
            # If there's a conversation history, use chat
            if len(gemini_messages) == 1 and "content" in gemini_messages[0]:
                # Simple single-turn generation
                response = await model.generate_content_async(
                    gemini_messages[0]["content"],
                    generation_config=generation_config,
                    tools=gemini_tools,
                )
            else:
                # Multi-turn conversation or complex messages
                # Use start_chat with full history
                chat = model.start_chat(history=gemini_messages[:-1])
                last_message = gemini_messages[-1]

                # Send the last message
                if "content" in last_message:
                    response = await chat.send_message_async(
                        last_message["content"],
                        generation_config=generation_config,
                        tools=gemini_tools,
                    )
                else:
                    # Last message has parts (e.g., FunctionResponse)
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
                        # Convert Gemini function call to OpenAI format
                        function_calls.append({
                            "id": f"call_{hash(fc.name)}",  # Gemini doesn't provide IDs
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

                # Combine text parts
                content = "".join(text_parts)

            # Get finish reason
            finish_reason = response.candidates[0].finish_reason.name if response.candidates else "UNKNOWN"

            # Extract usage information if available
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
            }

            return LLMResult(
                provider=self.name,
                model=model_name,
                content=content,
                finish_reason=finish_reason,
                usage=usage_dict,
                raw_response_id=None,  # Gemini doesn't provide response IDs in the same way
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

            # Handle system messages by prepending to first user message
            if role == "system":
                system_content = content
                continue

            # Handle tool result messages
            if role == "tool":
                # Tool results are represented as function responses in Gemini
                tool_name = msg.get("name", "")
                func_response = FunctionResponse(
                    name=tool_name,
                    response={"result": content}  # Wrap content as result
                )
                gemini_messages.append({
                    "role": "user",  # Tool results come back as user messages
                    "parts": [Part(function_response=func_response)],
                })
                continue

            # Convert role names
            gemini_role = "model" if role == "assistant" else "user"

            # If we have a system message and this is the first user message, prepend it
            if system_content and gemini_role == "user" and not gemini_messages:
                content = f"{system_content}\n\n{content}"
                system_content = None

            gemini_messages.append({
                "role": gemini_role,
                "parts": [content] if isinstance(content, str) else content,
            })

        # For simple generation (single message), return content directly
        if len(gemini_messages) == 1:
            parts = gemini_messages[0].get("parts", [])
            if parts and isinstance(parts[0], str):
                return [{"content": parts[0]}]

        return gemini_messages

    def _convert_tools_to_gemini(self, openai_tools: list[dict[str, Any]]) -> list[Any]:
        """
        Convert OpenAI-format tools to Gemini function declarations.

        OpenAI format:
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "...",
                "parameters": {"type": "object", "properties": {...}}
            }
        }

        Gemini format: Uses genai.protos.Tool with FunctionDeclaration
        """
        from google.ai.generativelanguage_v1beta.types import FunctionDeclaration, Schema, Type

        function_declarations = []

        for tool in openai_tools:
            if tool.get("type") != "function":
                continue

            func_def = tool.get("function", {})
            name = func_def.get("name")
            description = func_def.get("description", "")
            parameters = func_def.get("parameters", {})

            # Convert parameter schema
            gemini_params = self._convert_schema_to_gemini(parameters)

            # Create function declaration
            func_decl = FunctionDeclaration(
                name=name,
                description=description,
                parameters=gemini_params,
            )

            function_declarations.append(func_decl)

        # Return as Gemini Tool object
        if function_declarations:
            from google.ai.generativelanguage_v1beta.types import Tool
            return [Tool(function_declarations=function_declarations)]

        return None

    def _convert_schema_to_gemini(self, openai_schema: dict[str, Any]) -> Schema:
        """Convert OpenAI JSON schema to Gemini Schema."""
        from google.ai.generativelanguage_v1beta.types import Schema, Type

        # Map JSON types to Gemini types
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

        # Handle properties for objects
        if schema_type == "object" and "properties" in openai_schema:
            properties = {}
            for prop_name, prop_schema in openai_schema["properties"].items():
                properties[prop_name] = self._convert_schema_to_gemini(prop_schema)
            schema_kwargs["properties"] = properties

        # Handle required fields
        if "required" in openai_schema:
            schema_kwargs["required"] = openai_schema["required"]

        # Handle description
        if "description" in openai_schema:
            schema_kwargs["description"] = openai_schema["description"]

        # Handle enum
        if "enum" in openai_schema:
            schema_kwargs["enum"] = openai_schema["enum"]

        # Handle array items
        if schema_type == "array" and "items" in openai_schema:
            schema_kwargs["items"] = self._convert_schema_to_gemini(openai_schema["items"])

        return Schema(**schema_kwargs)
