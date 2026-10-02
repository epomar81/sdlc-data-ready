from typing import Any


def story_data() -> dict[str, Any]:
    return {
        "ID": "SHOP-1",
        "title": "Track an order",
        "Who": "Customer",
        "Action_What": "View order status",
        "Benefit_Why": "Know when to expect delivery",
        "Priority": "HIGH",
        "acceptance_criteria": [
            {
                "Scenario": "View a shipped order",
                "Given": "An order has shipped",
                "When": "The customer opens the order",
                "Then": "The shipping status is displayed",
            }
        ],
        "tags": [],
        "clarification": "",
        "suggestions": [],
    }


def settings_data() -> dict[str, Any]:
    return {
        "provider": "gemini",
        "model": "configured-model",
        "gemini_api_key": "test-credential",
        "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "nvidia_api_key": None,
        "nvidia_base_url": None,
        "max_retries": 2,
        "request_timeout_seconds": 30.0,
        "session_timeout_seconds": 120.0,
        "max_input_bytes": 65536,
        "schema_error_rate_threshold": 0.5,
        "schema_error_min_attempts": 2,
        "otel_service_name": "story-slicer",
        "otel_exporter_otlp_endpoint": "https://telemetry.example.test",
        "otel_export_interval_seconds": 30.0,
        "otel_export_timeout_seconds": 5.0,
    }
