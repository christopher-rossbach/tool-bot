"""LLM tool calling engine with OpenAI and Anthropic support."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from tool_bot.config import Config

logger = logging.getLogger(__name__)


# Tool schemas
class FlashcardCreate(BaseModel):
    """Schema for creating an Anki flashcard."""
    card_type: Literal["basic", "cloze", "basic-reversed"] = Field(
        description="Type of flashcard"
    )
    front: str = Field(description="Front of the card (question)")
    back: str = Field(description="Back of the card (answer)")
    deck: str = Field(description="Name of the Anki deck", default="Default")
    tags: List[str] = Field(description="Tags for the card", default_factory=list)


class TodoCreate(BaseModel):
    """Schema for creating a Todoist todo."""
    content: str = Field(description="Todo content/description")
    due_string: Optional[str] = Field(
        description="Natural language due date (e.g., 'tomorrow', 'next Monday')",
        default=None
    )
    priority: Literal[1, 2, 3, 4] = Field(
        description="Priority level (1=normal, 4=urgent)", default=1
    )
    labels: List[str] = Field(description="Labels for the todo", default_factory=list)
    project_name: Optional[str] = Field(
        description="Project name (will be created if doesn't exist)", default=None
    )


class WebSearch(BaseModel):
    """Schema for performing a web search."""
    query: str = Field(description="Search query to look up on the web")
    max_results: int = Field(
        description="Maximum number of results to return (1-10)", 
        default=5,
        ge=1,
        le=10
    )


class ToolCall(BaseModel):
    """Represents a tool call from the LLM."""
    tool_name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


class LLMEngine:
    """LLM tool-calling engine supporting OpenAI and Anthropic."""
    
    def __init__(self, config: Config):
        self.config = config
        self.provider = config.llm_provider.lower()
        
        # Initialize client based on provider
        if self.provider == "openai":
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=config.openai_api_key)
        elif self.provider == "anthropic":
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=config.anthropic_api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
    
    def _get_tools_schema(self) -> List[Dict]:
        """Get tool definitions for the LLM."""
        if self.provider == "openai":
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "create_flashcards",
                        "description": "Create Anki flashcards for learning. IMPORTANT: If the user says 'a flashcard' or 'one flashcard', create exactly ONE. If they say 'flashcards' or 'N flashcards', create that exact number. Never create more than requested.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "flashcards": {
                                    "type": "array",
                                    "items": FlashcardCreate.model_json_schema(),
                                    "description": "Array of flashcards to create. If user says 'a flashcard', this array should contain exactly 1 item."
                                }
                            },
                            "required": ["flashcards"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_todos",
                        "description": "Create Todoist todos/tasks. IMPORTANT: If the user says 'a todo' or 'one todo', create exactly ONE. If they say 'todos' or 'N todos', create that exact number. Never create more than requested.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "todos": {
                                    "type": "array",
                                    "items": TodoCreate.model_json_schema(),
                                    "description": "Array of todos to create. If user says 'a todo', this array should contain exactly 1 item."
                                }
                            },
                            "required": ["todos"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web for current information using DuckDuckGo. Use this when you need up-to-date information, facts, or details that you don't have in your training data.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query to look up on the web"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Maximum number of results to return (1-10)",
                                    "default": 5,
                                    "minimum": 1,
                                    "maximum": 10
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }
            ]
        else:  # Anthropic
            return [
                {
                    "name": "create_flashcards",
                    "description": "Create Anki flashcards for learning. IMPORTANT: If the user says 'a flashcard' or 'one flashcard', create exactly ONE. If they say 'flashcards' or 'N flashcards', create that exact number. Never create more than requested.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "flashcards": {
                                "type": "array",
                                "items": FlashcardCreate.model_json_schema(),
                                "description": "Array of flashcards to create. If user says 'a flashcard', this array should contain exactly 1 item."
                            }
                        },
                        "required": ["flashcards"]
                    }
                },
                {
                    "name": "create_todos",
                    "description": "Create Todoist todos/tasks. IMPORTANT: If the user says 'a todo' or 'one todo', create exactly ONE. If they say 'todos' or 'N todos', create that exact number. Never create more than requested.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "todos": {
                                "type": "array",
                                "items": TodoCreate.model_json_schema(),
                                "description": "Array of todos to create. If user says 'a todo', this array should contain exactly 1 item."
                            }
                        },
                        "required": ["todos"]
                    }
                },
                {
                    "name": "web_search",
                    "description": "Search the web for current information using DuckDuckGo. Use this when you need up-to-date information, facts, or details that you don't have in your training data.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query to look up on the web"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results to return (1-10)",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 10
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]
    
    async def process_message(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        enable_tools: bool = True,
    ) -> tuple[Optional[str], List[ToolCall]]:
        """
        Process a message with the LLM and extract tool calls.
        
        Args:
            system_prompt: System prompt for the LLM
            messages: Message history
            enable_tools: Whether to enable tool calling (default: True)
        
        Returns:
            (response_text, tool_calls)
        """
        if self.provider == "openai":
            return await self._process_openai(system_prompt, messages, enable_tools)
        else:
            return await self._process_anthropic(system_prompt, messages, enable_tools)
    
    async def _process_openai(
        self, system_prompt: str, messages: List[Dict[str, str]], enable_tools: bool = True
    ) -> tuple[Optional[str], List[ToolCall]]:
        """Process with OpenAI."""
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        
        kwargs = {
            "model": "gpt-4o-mini",  # or gpt-4o for more capable model
            "messages": full_messages,
        }
        
        # Add tools only if enabled
        if enable_tools:
            kwargs["tools"] = self._get_tools_schema()
            kwargs["tool_choice"] = "auto"
        
        response = await self.client.chat.completions.create(**kwargs)
        
        message = response.choices[0].message
        text = message.content
        tool_calls = []
        
        if enable_tools and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        tool_name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                        call_id=tc.id,
                    )
                )
        
        return text, tool_calls
    
    async def _process_anthropic(
        self, system_prompt: str, messages: List[Dict[str, str]], enable_tools: bool = True
    ) -> tuple[Optional[str], List[ToolCall]]:
        """Process with Anthropic."""
        kwargs = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
        }
        
        # Add tools only if enabled
        if enable_tools:
            kwargs["tools"] = self._get_tools_schema()
        
        response = await self.client.messages.create(**kwargs)
        
        text = None
        tool_calls = []
        
        for block in response.content:
            if block.type == "text":
                text = block.text
            elif enable_tools and block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        tool_name=block.name,
                        arguments=block.input,
                        call_id=block.id,
                    )
                )
        
        return text, tool_calls
