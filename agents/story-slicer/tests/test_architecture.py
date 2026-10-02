import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_domain_dependency_boundary() -> None:
    for path in (ROOT / "src/story_slicer/domain").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] in {"typing", "pydantic"}
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                assert node.module is not None
                assert node.module.split(".")[0] in {"typing", "pydantic", "__future__"}


def test_handwritten_functions_have_at_most_two_parameters() -> None:
    paths = list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
    assert paths
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs]
                count = len(parameters) - bool(
                    parameters and parameters[0].arg in {"self", "cls"}
                )
                assert count <= 2, (
                    f"{path}:{node.lineno} {node.name} has {count} parameters"
                )
                assert args.vararg is None and args.kwarg is None, (
                    f"{path}:{node.lineno} uses variadic arguments"
                )
