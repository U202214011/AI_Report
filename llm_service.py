from typing import Dict, Any, Generator
import os
from zai import ZhipuAiClient

def stream_glm_report(
    prompt: str,
    model: str = "glm-4.7-flash",
    max_tokens: int = 65536,
    temperature: float = 1.0,
    thinking_enabled: bool = True
) -> Generator[Dict[str, Any], None, None]:
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key:
        raise ValueError("Missing ZHIPUAI_API_KEY environment variable")

    client = ZhipuAiClient(api_key=api_key)

    request_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    if thinking_enabled:
        request_kwargs["thinking"] = {"type": "enabled"}

    response = client.chat.completions.create(**request_kwargs)

    for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "reasoning_content", None):
            yield {"type": "reasoning", "content": delta.reasoning_content}
        if getattr(delta, "content", None):
            yield {"type": "content", "content": delta.content}