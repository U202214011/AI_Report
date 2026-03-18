from typing import Dict, Any

def adapt_report_output(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meta": {"schema": "chinook-report-v1"},
        "summary": raw.get("summary", {}),
        "plots": raw.get("plots", []),
        "tables": raw.get("tables", []),
        "data": raw.get("data", []),
        "prompt": raw.get("prompt"),           # 添加这行
        "promptData": raw.get("promptData"),   # 添加这行（如果需要）
        "templateDebug": raw.get("templateDebug", {}),  # 添加这行
        "message": raw.get("message")
    }