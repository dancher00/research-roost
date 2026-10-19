from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


class PrivateWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.environment = dict(os.environ)
        self.environment.pop("PHD_SEARCH_WORKSPACE", None)
        self.environment.pop("RESEARCH_ROOST_WORKSPACE", None)
        self.environment["PYTHONPATH"] = str(PROJECT)

    def cli(self, root, *arguments, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "phd_search", "--workspace", str(root), *arguments],
            cwd=self.base, env=self.environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if result.stdout else result.stderr)

    def document(self, root, source, category="cv", expected=0):
        return self.cli(root, "profile", "document", "--file", str(source), "--category", category, expected=expected)

    def test_same_basename_preserves_both_versions_and_reimport_is_idempotent(self):
        root = self.base / "workspace"
        self.cli(root, "init")
        sources = []
        for folder, content in (("first", b"First original CV\n"), ("second", b"Second original CV\n")):
            source = self.base / folder / "cv.txt"
            source.parent.mkdir()
            source.write_bytes(content)
            sources.append(source)
        first = self.document(root, sources[0])
        first_directory = (root / first["file"]).parent
        first_saved = {path: path.read_bytes() for path in first_directory.iterdir()}
        for path in first_saved:
            os.utime(path, (1_000_000_000, 1_000_000_000))
        first_times = {path: path.stat().st_mtime_ns for path in first_saved}
        second = self.document(root, sources[1])
        self.assertNotEqual(first["file"], second["file"])
        for metadata, source in zip((first, second), sources):
            self.assertEqual((root / metadata["file"]).read_bytes(), source.read_bytes())
            self.assertEqual(metadata["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            paths = {root / metadata["file"], root / metadata["text_file"], (root / metadata["file"]).parent / "metadata.json"}
            self.assertEqual(len(paths), 3)
        self.assertEqual(self.document(root, sources[0]), first)
        self.assertEqual({path: path.read_bytes() for path in first_saved}, first_saved)
        self.assertEqual({path: path.stat().st_mtime_ns for path in first_saved}, first_times)
        self.assertEqual([path.read_bytes() for path in sources], [b"First original CV\n", b"Second original CV\n"])

    def test_original_html_is_separate_from_extraction_and_legacy_files_survive(self):
        root = self.base / "workspace"
        self.cli(root, "init")
        source = self.base / "cv.html"
        body = b'<html><h1>Candidate CV</h1><p>Evidence</p><div hidden>Hidden material</div></html>'
        source.write_bytes(body)
        legacy = root / "documents" / "cv" / "legacy-cv.html"
        legacy.parent.mkdir()
        legacy.write_bytes(b"Older preserved original")
        legacy_metadata = legacy.with_name(legacy.name + ".metadata.json")
        legacy_metadata.write_text('{"old":"metadata"}')
        registered = self.document(root, source)
        self.assertEqual((root / registered["file"]).read_bytes(), body)
        self.assertNotEqual((root / registered["text_file"]).read_bytes(), body)
        self.assertEqual(source.read_bytes(), body)
        self.assertEqual(legacy.read_bytes(), b"Older preserved original")
        self.assertEqual(legacy_metadata.read_text(), '{"old":"metadata"}')

    def test_reimport_never_repairs_changed_preserved_original_by_overwriting_it(self):
        root = self.base / "workspace"
        self.cli(root, "init")
        source = self.base / "cv.txt"
        source.write_text("Original source document\n")
        registered = self.document(root, source)
        saved = root / registered["file"]
        saved.write_text("Locally changed preserved file\n")
        result = self.document(root, source, expected=2)
        self.assertIn("not overwritten", result["error"])
        self.assertEqual(saved.read_text(), "Locally changed preserved file\n")
        self.assertEqual(source.read_text(), "Original source document\n")

    def test_unextractable_documents_are_preserved_and_repeatable(self):
        root = self.base / "workspace"
        self.cli(root, "init")
        source = self.base / "portfolio.bin"
        source.write_bytes(b"\x00\xffOriginal binary")
        registered = self.document(root, source, "portfolio")
        self.assertEqual(registered["extraction"], "unavailable")
        self.assertNotIn("text_file", registered)
        self.assertEqual(self.document(root, source, "portfolio"), registered)
        self.assertEqual((root / registered["file"]).read_bytes(), source.read_bytes())

    def test_init_preserves_existing_ignore_and_profile_with_idempotent_private_marker(self):
        root = self.base / "chosen workspace"
        root.mkdir()
        marker = root / ".gitignore"
        marker.write_text("# Existing local rule\n!keep.txt\n")
        self.cli(root, "init")
        self.cli(root, "profile", "fact", "--claim", "Confirmed synthetic fact", "--source", "Test confirmation")
        previous_profile = (root / "profile.json").read_bytes()
        previous_marker = marker.read_bytes()
        self.cli(root, "init")
        self.assertEqual(marker.read_bytes(), previous_marker)
        self.assertTrue(marker.read_text().startswith("# Existing local rule\n!keep.txt\n"))
        self.assertTrue(marker.read_text().endswith("*\n"))
        self.assertEqual((root / "profile.json").read_bytes(), previous_profile)

    def test_all_reset_scopes_preserve_private_archive_and_expected_retained_data(self):
        for scope in ("profile", "state", "all"):
            with self.subTest(scope=scope):
                root = self.base / scope / "workspace"
                self.cli(root, "init")
                self.cli(root, "profile", "fact", "--claim", "Synthetic private fact", "--source", "Test confirmation")
                source = self.base / (scope + "-cv.txt")
                source.write_text("Synthetic original candidate document\n")
                registered = self.document(root, source)
                previous_profile = (root / "profile.json").read_bytes()
                # A workspace created by an older version has no local marker.
                (root / ".gitignore").unlink()
                plan = self.cli(root, "reset", "--scope", scope)
                self.assertFalse(plan["executed"])
                self.assertFalse((root / ".gitignore").exists())
                result = self.cli(root, "reset", "--scope", scope, "--execute")
                archive = Path(result["archive"])
                self.assertTrue(result["executed"])
                self.assertTrue((root / ".gitignore").is_file())
                if scope == "profile":
                    self.assertEqual(archive.read_bytes(), previous_profile)
                    self.assertTrue((root / registered["file"]).is_file())
                else:
                    self.assertEqual((archive / "profile.json").read_bytes(), previous_profile)
                    self.assertEqual((archive / registered["file"]).read_bytes(), source.read_bytes())
                    self.assertTrue((archive / ".gitignore").read_text().endswith("*\n"))
                    self.assertEqual((root / registered["file"]).exists(), scope == "state")
                current = self.cli(root, "profile", "show")
                self.assertEqual(bool(current["facts"]), scope == "state")

    @unittest.skipUnless(shutil.which("git"), "git is unavailable")
    def test_real_git_ignores_default_legacy_and_custom_reset_archives(self):
        repo = self.base / "repository"
        repo.mkdir()
        shutil.copyfile(PROJECT / ".gitignore", repo / ".gitignore")

        def git(*arguments, expected=0):
            result = subprocess.run(
                ["git", "-c", "core.excludesFile=" + os.devnull, "-C", str(repo), *arguments],
                env=self.environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return result.stdout

        git("init", "-q")
        legacy = repo / "workspace-archived-before-fix" / "profile.json"
        legacy.parent.mkdir()
        legacy.write_text('{"private":"legacy archive"}')
        ignored = [legacy]
        for name in ("workspace", "custom private search"):
            root = repo / name
            self.cli(root, "init")
            self.cli(root, "profile", "fact", "--claim", "Synthetic private fact", "--source", "Test confirmation")
            ignored.append(root / "profile.json")
            result = self.cli(root, "reset", "--scope", "all", "--execute")
            ignored.extend([Path(result["archive"]) / "profile.json", root / "profile.json"])
        for path in ignored:
            with self.subTest(path=path.relative_to(repo)):
                self.assertTrue(git("check-ignore", "--", str(path)).strip())
        status = git("status", "--porcelain", "--untracked-files=all")
        self.assertEqual(status.strip(), "?? .gitignore")

    @unittest.skipUnless(shutil.which("bash"), "bash launcher is unavailable")
    def test_launcher_defaults_to_its_directory_honours_environment_and_explicit_override(self):
        repo = self.base / "launcher repository"
        repo.mkdir()
        launcher = repo / "phd"
        shutil.copyfile(PROJECT / "phd", launcher)
        selected = self.base / "environment workspace"
        override = self.base / "explicit workspace"
        for environment_root, arguments, expected in (
            (None, ["init"], repo / "workspace"),
            (selected, ["init"], selected),
            (selected, ["--workspace", str(override), "init"], override),
        ):
            with self.subTest(expected=expected):
                environment = dict(self.environment)
                if environment_root:
                    environment["PHD_SEARCH_WORKSPACE"] = str(environment_root)
                result = subprocess.run(
                    ["bash", str(launcher), *arguments], cwd=self.base, env=environment,
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["workspace"], str(expected))
                self.assertTrue((expected / "profile.json").is_file())


if __name__ == "__main__":
    unittest.main()
