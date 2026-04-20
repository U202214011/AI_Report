from typing import Dict, Any


def adapt_report_output(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meta": raw.get("meta", {"schema": "universal-report-v2"}),
        "summary": raw.get("summary", {}),
        "plots": raw.get("plots", []),
        "tables": raw.get("tables", []),
        "data": raw.get("data", []),
        "prompt": raw.get("prompt"),
        "finalPrompt": raw.get("finalPrompt", raw.get("prompt")),
        "promptData": raw.get("promptData"),
        "templateDebug": raw.get("templateDebug", {}),
        "message": raw.get("message")
    }