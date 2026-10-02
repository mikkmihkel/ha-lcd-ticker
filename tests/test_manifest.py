"""Static checks for the integration's metadata files."""

import json
from pathlib import Path

from scripts.build_translations import build

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "lcd_ticker"


def test_manifest_has_required_fields() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    for key in (
        "domain",
        "name",
        "version",
        "documentation",
        "issue_tracker",
        "codeowners",
    ):
        assert manifest[key]
    assert manifest["domain"] == "lcd_ticker"
    assert manifest["requirements"] == []
    assert manifest["config_flow"] is True


def test_hacs_json() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"] == "LCD Ticker"
    assert hacs["homeassistant"] == "2026.3.0"
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "lcd_ticker.zip"


def test_translations_are_built_from_strings() -> None:
    built = (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    assert built == build(), "run: python scripts/build_translations.py"
