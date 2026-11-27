"""Tests for decide's served-model check. Offline: every reply is a --replay fixture.

decide is a C# file-based app, so these build it with the dotnet SDK on PATH. The first run builds
and caches it (a few seconds to a minute); later runs reuse the build. Run from this directory
inside a sandbox (for example a bubblewrap wrapper):
    python3 -m unittest test_decide -v

Inside the sandbox the home directory is read-only and there is no network, so the packages the
build needs must already be in the NuGet cache (run `dotnet restore decide.cs` once outside it).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "decide")
EXIT_YES, EXIT_API = 0, 4


def _environment(scratch: str) -> dict[str, str]:
    """dotnet writes its first-run, run-file and mutex state under these; point them at scratch."""
    env = dict(os.environ)
    for name in ("DOTNET_CLI_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        path = os.path.join(scratch, name.lower())
        os.makedirs(path, mode=0o700, exist_ok=True)
        env[name] = path
    nuget = os.path.join(os.path.expanduser("~"), ".nuget", "packages")
    env.setdefault("NUGET_PACKAGES", nuget)
    env.setdefault("RestoreSources", nuget)
    env.update(DOTNET_NOLOGO="1", DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    env.pop("DECIDE_MODEL", None)
    env.pop("DECIDE_SERVED_MODEL", None)
    env["DECIDE_LOG"] = os.path.join(scratch, "decide.jsonl")
    return env


@unittest.skipIf(shutil.which("dotnet") is None, "dotnet SDK not on PATH")
class ServedModelCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.mkdtemp(prefix="decide-test-")
        cls.env = _environment(cls._scratch)
        # Fail loudly if the app cannot build at all, so a build fault is not read as a verdict.
        built = subprocess.run([SHIM, "--help"], env=cls.env, capture_output=True, text=True, timeout=600)
        if "Usage: decide" not in built.stdout:
            raise RuntimeError(f"decide did not build or run:\n{built.stdout}\n{built.stderr}")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._scratch, ignore_errors=True)

    def ask(
        self,
        requested: str,
        served: str | None,
        probability: float = 0.95,
        extra: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        body: dict[str, object] = {"id": "x", "answers": {"decision": {"type": "noul", "noul": probability}}}
        if served is not None:
            body["model"] = served
        path = os.path.join(self._scratch, "reply.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        return subprocess.run(
            [SHIM, "--replay", path, "--model", requested, *(extra or []), "ask", "--state", "{}", "--yes-no", "Ready?"],
            env={**self.env, **(env or {})}, capture_output=True, text=True, timeout=300,
        )

    def test_same_model_answers(self) -> None:
        result = self.ask("inception/mercury-decide:free", "inception/mercury-decide:free")
        self.assertEqual(result.returncode, EXIT_YES, result.stderr)
        self.assertIn("p(yes)=0.950", result.stdout)

    def test_another_model_is_refused(self) -> None:
        result = self.ask("inception/mercury-decide:free", "openai/gpt-4o-mini")
        self.assertEqual(result.returncode, EXIT_API, result.stdout)
        self.assertIn("served by openai/gpt-4o-mini", result.stderr)
        self.assertIn("inception/mercury-decide:free", result.stderr)
        self.assertNotIn("p(yes)", result.stdout, "an answer from another model must not be printed")

    def test_renamed_model_is_refused_without_an_alias(self) -> None:
        # Exact by design: a gateway answering with its own deployment name is not guessed at.
        for requested, served in [
            ("example/decide-model", "decide-model"),
            ("inception/mercury-decide:free", "inception/mercury-decide"),
            ("example/decide-model", "decide-model-lite"),
        ]:
            with self.subTest(requested=requested, served=served):
                result = self.ask(requested, served)
                self.assertEqual(result.returncode, EXIT_API, result.stdout)
                self.assertIn(f"served by {served};", result.stderr)

    def test_alias_flag_accepts_the_named_reply(self) -> None:
        result = self.ask("example/decide-model", "decide-model", extra=["--served-as", "decide-model"])
        self.assertEqual(result.returncode, EXIT_YES, result.stderr)

    def test_alias_variable_accepts_the_named_reply(self) -> None:
        result = self.ask("example/decide-model", "decide-model", env={"DECIDE_SERVED_MODEL": "decide-model"})
        self.assertEqual(result.returncode, EXIT_YES, result.stderr)

    def test_alias_still_refuses_a_third_model(self) -> None:
        result = self.ask("example/decide-model", "openai/gpt-4o-mini", extra=["--served-as", "decide-model"])
        self.assertEqual(result.returncode, EXIT_API, result.stdout)
        self.assertIn("expected decide-model", result.stderr)

    def test_missing_model_field_answers_with_a_warning(self) -> None:
        result = self.ask("inception/mercury-decide:free", None)
        self.assertEqual(result.returncode, EXIT_YES, result.stderr)
        self.assertIn("did not say which model", result.stderr)


if __name__ == "__main__":
    unittest.main()
