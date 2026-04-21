from typing import Dict, Any, Generator, List
import os
from zai import ZhipuAiClient
from dotenv import load_dotenv

load_dotenv()

def _estimate_tokens_from_text(text: str) -> int:
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

def estimate_messages_chars(messages: List[Dict[str, Any]]) -> int:
    """Return total character count across all message contents."""
    return sum(len(str(m.get("content", ""))) for m in messages or [])

def _extract_delta_fields(delta):
    rc = (
        getattr(delta, "reasoning_content", None)
        or getattr(delta, "thinking_content", None)
        or getattr(delta, "reasoning", None)
        or getattr(delta, "thinking", None)
    )
    cc = (
        getattr(delta, "content", None)
        or getattr(delta, "message", None)
        or getattr(delta, "text", None)
    )
    return rc, cc


def stream_glm_chat(
    messages: List[Dict[str, Any]],
    model: str = "glm-4.7-flash",
    max_tokens: int = 65536,
    temperature: float = 0.7,
    thinking_enabled: bool = True
) -> Generator[Dict[str, Any], None, None]:
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key:
        err = "Missing ZHIPUAI_API_KEY environment variable"
        print(f"[LLM] ERROR: {err}")
        yield {"type": "error", "content": err}
        return

    try:
        print(f"[LLM] API key exists: {bool(api_key)}, length: {len(api_key) if api_key else 0}")
        # ✅ 只保留这一个 client 创建，使用正确的 api_key 变量
        client = ZhipuAiClient(api_key=api_key)
        print(f"[LLM] Client created successfully")

        print(f"[LLM] start model={model}, max_tokens={max_tokens}, temperature={temperature}, thinking_enabled={thinking_enabled}")
        print(f"[LLM] messages_count={len(messages)}")
        if messages:
            last = messages[-1]
            print(f"[LLM] last_role={last.get('role')}, last_content_len={len(str(last.get('content','')))}")


        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if thinking_enabled:
            request_kwargs["thinking"] = {"type": "enabled"}

        print(f"[LLM] request_kwargs_keys={list(request_kwargs.keys())}")
        response = client.chat.completions.create(**request_kwargs)

        chunk_count = 0
        reasoning_chars = 0
        content_chars = 0

        for chunk in response:
            chunk_count += 1

            # 如果需要排查字段，打开下一行
            # print(f"[LLM] raw_chunk={chunk}")

            if chunk_count <= 3:
                print(f"[LLM] chunk#{chunk_count} available_attrs={[a for a in dir(chunk) if not a.startswith('_')]}")

            if not getattr(chunk, "choices", None):
                continue

            delta = chunk.choices[0].delta
            rc, cc = _extract_delta_fields(delta)

            if rc:
                reasoning_chars += len(rc)
                yield {"type": "reasoning", "content": rc}
            if cc:
                content_chars += len(cc)
                yield {"type": "content", "content": cc}

        print(f"[LLM] done chunk_count={chunk_count}, reasoning_chars={reasoning_chars}, content_chars={content_chars}")

        # 如果流式没有任何内容，则回退非流式
        if content_chars == 0 and reasoning_chars == 0:
            print("[LLM] stream empty, fallback to non-stream response (check API key and model support)")
            fallback_kwargs = dict(request_kwargs)
            fallback_kwargs["stream"] = False
            response = client.chat.completions.create(**fallback_kwargs)

            # 兼容不同返回结构
            try:
                msg = response.choices[0].message
                content = getattr(msg, "content", "") or getattr(msg, "text", "")
                reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "thinking_content", None)
            except Exception:
                content = ""
                reasoning = None

            if reasoning:
                yield {"type": "reasoning", "content": reasoning}
            if content:
                yield {"type": "content", "content": content}
            if not content and not reasoning:
                yield {"type": "error", "content": "LLM返回为空（stream与非stream均无内容）"}

    except Exception as e:
        err = f"LLM调用失败: {str(e)}"
        print(f"[LLM] EXCEPTION: {err}")
        yield {"type": "error", "content": err}

def stream_glm_report(
    prompt: str,
    model: str = "glm-4.7-flash",
    max_tokens: int = 65536,
    temperature: float = 1.0,
    thinking_enabled: bool = True
) -> Generator[Dict[str, Any], None, None]:
    messages = [{"role": "user", "content": prompt}]
    for chunk in stream_glm_chat(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking_enabled=thinking_enabled
    ):
        yield chunk