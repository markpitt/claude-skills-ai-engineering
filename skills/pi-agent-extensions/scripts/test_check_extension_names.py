"""Tests for check_extension_names.py. Fixtures are written at run time in a temporary directory.

Run inside a sandbox (for example a bubblewrap wrapper) for test runs:
    python3 -P claude-skills-ai-engineering/skills/pi-agent-extensions/scripts/test_check_extension_names.py -v
"""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_extension_names.py"
sys.path.insert(0, str(SCRIPT.parent))

import check_extension_names as cen  # noqa: E402

FAKE_BINARY_STRINGS = b"\x00registerProvider\x00refreshModels\x00session_start\x00tool_call\x00confirm\x00"


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cen.main(argv)
    return code, out.getvalue(), err.getvalue()


class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.binary = self.dir / "pi-fake"
        self.binary.write_bytes(FAKE_BINARY_STRINGS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def ext(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_known_names_pass(self) -> None:
        f = self.ext(
            "good.ts",
            'export default function (pi) {\n'
            '  pi.on("session_start", async (_e, ctx) => { ctx.ui.confirm("a", "b"); });\n'
            '  pi.registerProvider("x", { refreshModels: async () => [] });\n'
            "}\n",
        )
        code, out, _ = run_main(["--binary", str(self.binary), str(f)])
        self.assertEqual(code, 0)
        self.assertIn("0 name(s) not found", out)

    def test_stale_method_name_is_reported_not_found(self) -> None:
        # Positive control for the failure path: a plausible but wrong method name must be flagged.
        f = self.ext("stale.ts", 'export default function (pi) { pi.registerModelProvider("x", {}); }\n')
        code, out, _ = run_main(["--binary", str(self.binary), str(f)])
        self.assertEqual(code, 1)
        self.assertIn("NOT FOUND  pi.registerModelProvider", out)

    def test_wrong_event_name_is_reported(self) -> None:
        f = self.ext("event.ts", 'export default function (pi) { pi.on("sesion_start", () => {}); }\n')
        code, out, _ = run_main(["--binary", str(self.binary), str(f)])
        self.assertEqual(code, 1)
        self.assertIn('NOT FOUND  pi.on("sesion_start")', out)

    def test_commented_out_stale_name_is_ignored(self) -> None:
        f = self.ext(
            "commented.ts",
            "export default function (pi) {\n"
            "  // pi.registerModelProvider(\"old\", {});\n"
            "  pi.registerProvider(\"x\", {});\n"
            "}\n",
        )
        code, out, _ = run_main(["--binary", str(self.binary), str(f)])
        self.assertEqual(code, 0)
        self.assertNotIn("registerModelProvider", out)

    def test_missing_binary_is_a_usage_error(self) -> None:
        f = self.ext("any.ts", "pi.registerProvider(\"x\", {});\n")
        code, _, err = run_main(["--binary", str(self.dir / "absent"), str(f)])
        self.assertEqual(code, 2)
        self.assertIn("no pi binary", err)

    def test_missing_extension_file_is_a_usage_error(self) -> None:
        code, _, err = run_main(["--binary", str(self.binary), str(self.dir / "absent.ts")])
        self.assertEqual(code, 2)
        self.assertIn("not a file", err)

    def test_file_with_no_names_says_so(self) -> None:
        f = self.ext("plain.ts", "export const x = 1;\n")
        code, out, _ = run_main(["--binary", str(self.binary), str(f)])
        self.assertEqual(code, 0)
        self.assertIn("no pi or ctx.ui names", out)

    def test_collect_separates_groups(self) -> None:
        f = self.ext("groups.ts", 'pi.on("tool_call", (e, ctx) => ctx.ui.notify("x", "info"));\npi.registerTool({});\n')
        names = cen.collect(f)
        self.assertEqual(names["event"], {"tool_call"})
        self.assertEqual(names["ctx.ui"], {"notify"})
        self.assertEqual(names["pi"], {"registerTool"})

    def test_real_binary_smoke_when_pi_is_installed(self) -> None:
        pi = shutil.which("pi")
        if pi is None:
            self.skipTest("pi is not on PATH in this environment")
        f = self.ext("real.ts", 'export default function (pi) { pi.registerProvider("x", {}); }\n')
        proc = subprocess.run(
            [sys.executable, "-I", "-P", str(SCRIPT), "--binary", pi, str(f)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
