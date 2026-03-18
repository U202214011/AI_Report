from typing import Dict, Any, Generator, List
import os
from zai import ZhipuAiClient

def _estimate_tokens_from_text(text: str) -> int:
    """
    粗略估算 token：
    - 中文约 1~1.5 字/token
    - 英文约 3~4 字符/token
    这里采用保守估算，宁可高估，便于提前预警。
    """
    if not text:
        return 0
    return max(1, int(len(text) / 1.6))

def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for m in messages or []:
        role = str(m.get("role", ""))
        content = str(m.get("content", ""))
        total += _estimate_tokens_from_text(role) + _estimate_tokens_from_text(content) + 6
    return total

def stream_glm_chat(
    messages: List[Dict[str, Any]],
    model: str = "glm-4.7-flash",
    max_tokens: int = 65536,
    temperature: float = 0.7,
    thinking_enabled: bool = True
) -> Generator[Dict[str, Any], None, None]:
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key:
        raise ValueError("Missing ZHIPUAI_API_KEY environment variable")

    client = ZhipuAiClient(api_key=api_key)

    request_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
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

def stream_glm_report(
    prompt: str,
    model: str = "glm-4.7-flash",
    max_tokens: int = 65536,
    temperature: float = 1.0,
    thinking_enabled: bool = True
) -> Generator[Dict[str, Any], None, None]:
    """
    向后兼容旧接口：单轮 prompt -> chat messages
    """
    messages = [{"role": "user", "content": prompt}]
    for chunk in stream_glm_chat(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking_enabled=thinking_enabled
    ):
        yield chunk