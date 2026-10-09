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


def render_feedback_comment(report: RefinementReport) -> str:
    suggested = [
        item.text.removeprefix("[IA ENHANCED]").strip()
        for item in report.suggestions
        if item.tag in {"AI_ENHANCED", "FEATURE_IDEA"}
    ]
    clarifications = [
        item.text for item in report.suggestions if item.tag == "CLARIFICATION"
    ]
    lines = ["### Suggested requirement"]
    for text in suggested:
        lines.extend(["", text])
    lines.append("")
    lines.append("### Clarifications")
    for question in clarifications:
        lines.extend(["", f"- {question}"])
    return "\n".join(lines)
