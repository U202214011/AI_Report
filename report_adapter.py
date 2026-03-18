from typing import Dict, Any

def adapt_report_output(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meta": {"schema": "chinook-report-v1"},
        "summary": raw.get("summary", {}),
        "plots": raw.get("plots", []),
        "tables": raw.get("tables", []),
        "data": raw.get("data", []),
        "message": raw.get("message")
    }