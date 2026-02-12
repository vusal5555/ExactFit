import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from typing import Optional, Type
from pydantic import BaseModel

load_dotenv()


def get_llm(model: str = "gpt-5-mini", temperature: float = 0) -> ChatOpenAI:
    """Get OpenAI LLM instance."""

    return ChatOpenAI(
        model=model, temperature=temperature, api_key=os.getenv("OPEN_AI_API_KEY")
    )


def invoke_llm(
    system_prompt: str,
    user_message: str,
    model: str = "gpt-5-mini",
    response_format: Optional[Type[BaseModel]] = None,
):
    """
    Invoke LLM with system prompt and user message.

    Args:
        system_prompt: Instructions for the LLM
        user_message: Content to process
        model: OpenAI model to use
        response_format: Optional Pydantic model for structured output

    Returns:
        String response or Pydantic model instance
    """

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    llm = get_llm(model)

    if response_format:
        llm = llm.with_structured_output(response_format)
    else:
        llm = llm | StrOutputParser()

    return llm.invoke(messages)


async def invoke_llm_async(
    system_prompt: str,
    user_message: str,
    model: str = "gpt-5-mini",
    response_format: Optional[Type[BaseModel]] = None,
):
    """Async version of invoke_llm."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    llm = get_llm(model)

    if response_format:
        llm = llm.with_structured_output(response_format)
    else:
        llm = llm | StrOutputParser()

    return await llm.ainvoke(messages)
