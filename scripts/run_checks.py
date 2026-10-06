"""Run existing quality gates and commit a compact, machine-readable verification result."""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    results = []
    with TemporaryDirectory() as temp:
        junit = str(Path(temp) / "pytest.xml")
        for args in (["ruff", "check", "."], ["mypy"], ["pytest", f"--junitxml={junit}"]):
            completed = subprocess.run([sys.executable, "-m", *args], check=False)
            results.append(
                {"command": "python -m " + " ".join(args[:1]), "exit_code": completed.returncode}
            )
        suites = ET.parse(junit).getroot()
        cases = list(suites.iter("testcase"))
        report = {
            "gates": results,
            "tests": len(cases),
            "failed": sum(
                c.find("failure") is not None or c.find("error") is not None for c in cases
            ),
            "skipped": [
                {"name": c.attrib["name"], "reason": c.find("skipped").attrib.get("message", "")}
                for c in cases
                if c.find("skipped") is not None
            ],
        }
    Path("evals/reports/checks.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if any(r["exit_code"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
