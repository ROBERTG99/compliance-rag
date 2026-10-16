"""LLM gateway: the only module that imports provider SDKs (Anthropic, OpenAI, Bedrock runtime)."""

from __future__ import annotations

from typing import Any

from compliance_rag.settings import get_settings


def bedrock_runtime_client() -> Any:
    import boto3

    return boto3.client("bedrock-runtime", region_name=get_settings().aws_region)


def openai_client() -> Any:
    import openai

    key = get_settings().openai_api_key
    return openai.OpenAI(api_key=key.get_secret_value() if key else None)
