"""Safe single-document YAML parsing with duplicate key rejection."""

from collections.abc import Hashable
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from story_slicer.adapters.requirements.refined import RefinedDocument
from story_slicer.domain.models import RequirementDocument
from story_slicer.ports.errors import InputError


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        self.flatten_mapping(node)
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable) or key in seen:
                raise ConstructorError(
                    None, None, "Invalid or duplicate YAML key", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


class YamlRequirementParser:
    def parse(self, content: bytes) -> RequirementDocument:
        try:
            data = yaml.load(content.decode("utf-8"), Loader=_UniqueKeyLoader)
            if isinstance(data, dict) and "initiative" in data:
                return RefinedDocument.model_validate(data).to_requirement()
            return RequirementDocument.model_validate(data)
        except ValidationError as error:
            details = "\n".join(
                f"  {'.'.join(map(str, issue['loc'])) or '<root>'}: {issue['msg']}"
                for issue in error.errors(include_input=False, include_url=False)
            )
            raise InputError(
                f"Requirement YAML violates the input schema:\n{details}"
            ) from None
        except UnicodeError:
            raise InputError("Requirement YAML must be UTF-8 encoded") from None
        except yaml.MarkedYAMLError as error:
            location = ""
            if error.problem_mark is not None:
                mark = error.problem_mark
                location = f" at line {mark.line + 1}, column {mark.column + 1}"
            # PyYAML's full exception includes source excerpts; display only the
            # problem and its position so requirement values remain private.
            raise InputError(
                f"Requirement YAML is malformed{location}: {error.problem}"
            ) from None
        except yaml.YAMLError:
            raise InputError("Requirement YAML is malformed") from None
        except RecursionError:
            raise InputError(
                "Requirement YAML exceeds the supported nesting depth"
            ) from None
