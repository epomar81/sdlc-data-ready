from intention_refiner.domain.models import RefinementReport


def adf_to_text(document: dict | None) -> str:
    if document is None:
        return ""
    if not isinstance(document, dict) or not isinstance(document.get("type"), str):
        raise TypeError("Invalid rich text document")
    kind = document["type"]
    children = document.get("content", [])
    if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
        raise TypeError("Invalid rich text content")
    attrs = document.get("attrs", {})
    if not isinstance(attrs, dict):
        raise TypeError("Invalid rich text attributes")
    if kind == "text":
        text = document.get("text")
        if not isinstance(text, str):
            raise TypeError("Invalid rich text node")
        marks = document.get("marks", [])
        if not isinstance(marks, list):
            raise TypeError("Invalid rich text marks")
        for mark in marks:
            if not isinstance(mark, dict):
                raise TypeError("Invalid rich text mark")
            if mark.get("type") == "link":
                link_attrs = mark.get("attrs", {})
                if not isinstance(link_attrs, dict) or not isinstance(
                    link_attrs.get("href"), str
                ):
                    raise TypeError("Invalid rich text link")
                text += f" ({link_attrs['href']})"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind in {"mention", "emoji", "inlineCard", "date"}:
        value = (
            attrs.get("text")
            or attrs.get("shortName")
            or attrs.get("url")
            or attrs.get("timestamp", "")
        )
        if not isinstance(value, str):
            raise TypeError("Invalid rich text attribute")
        return value
    separator = (
        " | "
        if kind == "tableRow"
        else "\n"
        if kind
        in {
            "doc",
            "bulletList",
            "orderedList",
            "table",
            "listItem",
            "blockquote",
            "panel",
        }
        else ""
    )
    text = separator.join(
        adf_to_text(child).rstrip("\n") if separator else adf_to_text(child)
        for child in children
    )
    if kind == "listItem":
        return "- " + text
    if kind == "codeBlock":
        return f"```\n{text}\n```\n"
    if kind in {"paragraph", "heading", "tableRow"}:
        return text + "\n"
    return text


def text_to_adf(text: str) -> dict:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            if line
            else {"type": "paragraph", "content": []}
            for line in text.splitlines()
        ],
    }


def render_result(report: RefinementReport) -> str:
    lines = ["Refinement result", "", "Extracted requirement"]
    lines.extend(
        f"- {name}: {value if value is not None else 'Unknown'}"
        for name, value in report.initiative.model_dump().items()
    )
    lines.extend(["", "Suggestions (proposed content for review)"])
    lines.extend(
        f"- [{item.tag}] {item.field_name}: {item.text}" for item in report.suggestions
    )
    lines.extend(["", "Audit"])
    for name, values in report.audit.model_dump().items():
        lines.extend(f"- {name}: {value}" for value in values)
    lines.extend(["", "Refinement proposals (for review)"])
    lines.extend(
        f"- {item.field_name}: {item.proposed_text}\n  Rationale: {item.rationale}"
        for item in report.refinement_proposals
    )
    return "\n".join(lines)


def render_questions(report: RefinementReport) -> str | None:
    questions = [item for item in report.suggestions if item.tag == "CLARIFICATION"]
    if not questions:
        return None
    lines = ["Clarification requested", ""]
    for field in dict.fromkeys(item.field_name for item in questions):
        lines.append(f"{field}:")
        lines.extend(
            f"- [CLARIFICATION] {item.text}"
            for item in questions
            if item.field_name == field
        )
    return "\n".join(lines)
