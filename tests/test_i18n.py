"""Every translatable GUI string has Swedish and German text with the same placeholders."""

import ast
import string
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from ps3005d.gui import i18n

GUI_DIR = Path(i18n.__file__).parent
# Passed to tr() through variables rather than as literals.
DYNAMIC_KEYS = {
    "Voltage",
    "Current",
    "Power",
    "not saved yet – saved when output is turned off",
    "saving failed – previous value shown",
    "saving…",
}


def _tr_literals() -> set[str]:
    found: set[str] = set()
    for path in GUI_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.add(node.args[0].value)
    return found


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_tr_calls_found() -> None:
    assert len(_tr_literals()) > 40


@pytest.mark.parametrize("key", sorted(_tr_literals() | DYNAMIC_KEYS))
def test_translated(key: str) -> None:
    assert key in i18n.STRINGS, f"missing translation entry for {key!r}"
    for lang in ("sv", "de"):
        text = i18n.STRINGS[key].get(lang)
        assert text, f"{key!r} has no {lang} translation"
        assert _fields(text) == _fields(key), f"placeholders differ in {lang}: {text!r}"


def test_no_unused_entries() -> None:
    unused = set(i18n.STRINGS) - _tr_literals() - DYNAMIC_KEYS
    assert not unused, f"unused translations: {sorted(unused)}"


def test_unknown_language_rejected() -> None:
    with pytest.raises(ValueError):
        i18n.set_language("fr")


def test_fallback_and_format() -> None:
    i18n.set_language("sv")
    try:
        assert i18n.tr("Connected: {identity}", identity="X") == "Ansluten: X"
        assert i18n.tr("untranslated text") == "untranslated text"
    finally:
        i18n.set_language("en")
