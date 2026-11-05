"""Shared adapter machinery.

The one rule adapters follow: a threshold's *value* is read out of the system
under test's source, never restated here. A declaration that duplicates the
number is a second copy that can drift from the first, and the drift is silent
precisely when it matters — the day someone tunes the constant and the register
still describes the old one.

Reading it from source also gives the value-binding on risk acceptances its
teeth: change `TEMP_LIMIT = 90.0` to `95.0` and the threshold's value_hash
moves, so the sign-off granted for 90.0 no longer applies.
"""

from __future__ import annotations

import ast
from pathlib import Path


class SourceConstantError(ValueError):
    pass


def read_constants(file: Path, names: set[str]) -> dict[str, tuple[float, int]]:
    """Read module-level numeric constants, returning value and line number.

    Parsed rather than imported so the harness does not need the system under
    test's dependencies installed, and so importing a module cannot execute
    anything on the way to reading a number out of it.
    """
    tree = ast.parse(file.read_text(encoding="utf-8"))
    found: dict[str, tuple[float, int]] = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                if not isinstance(node.value, ast.Constant) or not isinstance(
                    node.value.value, (int, float)
                ):
                    raise SourceConstantError(
                        f"{file.name}:{node.lineno} {target.id} is not a numeric "
                        "literal. A threshold computed at import time cannot be "
                        "pinned by value."
                    )
                found[target.id] = (float(node.value.value), node.lineno)

    missing = names - found.keys()
    if missing:
        raise SourceConstantError(
            f"{file}: expected constant(s) {sorted(missing)} not found. The "
            "adapter is describing code that no longer exists."
        )
    return found


def read_env_default(file: Path, name: str) -> tuple[float, int, str]:
    """Read `NAME = float(os.getenv("VAR", "<literal>"))`: the default, its line, the variable.

    A threshold taken from the environment is a deployment setting. The source
    pins only its default, so evidence gathered against the default does not
    describe a deployment that overrides it. This returns the default and the
    name of the variable that can override it so the caller can say exactly
    that, instead of either refusing to read the number or pretending the
    environment cannot change it.
    """
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        call = node.value
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in {"float", "int"}
            and len(call.args) == 1
        ):
            call = call.args[0]
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in {"getenv", "get"}
            and len(call.args) == 2
            and all(isinstance(a, ast.Constant) for a in call.args)
        ):
            variable, default = (a.value for a in call.args)
            try:
                return float(default), node.lineno, str(variable)
            except (TypeError, ValueError):
                pass
        raise SourceConstantError(
            f"{file.name}:{node.lineno} {name} is not `float(os.getenv(VAR, "
            "<literal>))`, so its default cannot be read by value."
        )
    raise SourceConstantError(f"{file}: expected constant {name!r} not found.")
