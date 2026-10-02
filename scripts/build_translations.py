"""Build translations/en.json from strings.json.

Home Assistant only resolves [%key:...%] references for core integrations, so a
custom integration must ship them already resolved. Run after editing strings.json:

    python scripts/build_translations.py
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "lcd_ticker"

COMMON = {
    "common::config_flow::abort::already_configured_device": "Device is already configured",
    "common::config_flow::abort::already_in_progress": "Configuration flow is already in progress",
    "common::config_flow::abort::reconfigure_successful": "Re-configuration was successful",
}
REF = re.compile(r"^\[%key:([^%]+)%\]$")


def _lookup(data: dict, path: str) -> str:
    if path in COMMON:
        return COMMON[path]
    prefix = "component::lcd_ticker::"
    if not path.startswith(prefix):
        raise KeyError(f"unknown translation reference: {path}")
    node = data
    for part in path.removeprefix(prefix).split("::"):
        node = node[part]
    return node


def resolve(node, data: dict):
    if isinstance(node, dict):
        return {key: resolve(value, data) for key, value in node.items()}
    if isinstance(node, str) and (match := REF.match(node)):
        return _lookup(data, match.group(1))
    return node


def build() -> str:
    data = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    return json.dumps(resolve(data, data), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    target = INTEGRATION / "translations" / "en.json"
    target.write_text(build(), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
