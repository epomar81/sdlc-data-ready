import os
import tempfile
from pathlib import Path

import yaml

from intention_refiner.domain.integration import RequirementInput, SourceReference
from intention_refiner.domain.models import RefinementReport


class TextFileReader:
    def read(self, path: Path | SourceReference) -> str | RequirementInput:
        if isinstance(path, SourceReference):
            return RequirementInput(Path(path.reference).read_text(encoding='utf-8'))
        return path.read_text(encoding='utf-8')


class YamlReportWriter:
    def write(self, report: RefinementReport, path: Path) -> None:
        data = report.model_dump(mode="json")
        metadata = {key: data.pop(key) for key in ("provider", "model", "response_time_ms")}
        source = data.pop("source", None)
        if source is not None:
            metadata["source"] = source
        data["metadata"] = metadata
        content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                suffix=".tmp", delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
