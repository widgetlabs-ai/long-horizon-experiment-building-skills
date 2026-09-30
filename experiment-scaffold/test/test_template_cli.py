"""The template CLI must turn an unforeseen exception into a broken substrate.

An uncaught exception exits 1, which the supervisor reads as "this candidate
lost" -- or, from `review`, as "the reviewer refused". No record is written,
the streak never moves, and the search silently stops adopting. The template
carries `__EXPERIMENT__` placeholders and cannot be imported, so this reads its
syntax tree instead.
"""

import ast
import unittest
from pathlib import Path

TEMPLATE_CLI = Path(__file__).resolve().parents[1] / "template" / "cli.py"


def _main(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("template/cli.py defines no main()")


class TemplateCliCatchAll(unittest.TestCase):
    def test_main_turns_any_exception_into_exit_substrate(self):
        main = _main(ast.parse(TEMPLATE_CLI.read_text()))
        handlers = [h for node in ast.walk(main) if isinstance(node, ast.Try) for h in node.handlers]
        catch_all = [h for h in handlers if isinstance(h.type, ast.Name) and h.type.id == "Exception"]
        self.assertTrue(catch_all, "main() has no `except Exception` block")
        returns = [n for h in catch_all for n in ast.walk(h) if isinstance(n, ast.Return)]
        self.assertTrue(
            any(isinstance(r.value, ast.Name) and r.value.id == "EXIT_SUBSTRATE" for r in returns),
            "main()'s `except Exception` block does not return EXIT_SUBSTRATE",
        )


if __name__ == "__main__":
    unittest.main()
