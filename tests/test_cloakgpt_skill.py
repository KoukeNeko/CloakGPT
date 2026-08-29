import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cloakgpt_skill


class BundledSkillTests(unittest.TestCase):
    def test_reads_the_skill_from_a_source_checkout(self) -> None:
        text = cloakgpt_skill.bundled_skill_text()

        self.assertIsNotNone(text)
        self.assertIn("name: use-cloakgpt", text)

    def test_reads_the_skill_from_a_packaged_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            packaged = bundle / "skills" / cloakgpt_skill.SKILL_NAME / "SKILL.md"
            packaged.parent.mkdir(parents=True)
            packaged.write_text("packaged skill", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "_MEIPASS", str(bundle), create=True):
                    self.assertEqual(
                        cloakgpt_skill.bundled_skill_text(), "packaged skill"
                    )


class OutdatedSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def _install(self, agent_dir: str, text: str) -> Path:
        path = self.home / agent_dir / "skills" / cloakgpt_skill.SKILL_NAME / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_reports_only_copies_that_differ(self) -> None:
        current = self._install(".claude", "shipped")
        stale = self._install(".gemini", "older")

        with patch.object(cloakgpt_skill, "_home_dir", return_value=self.home):
            outdated = cloakgpt_skill.outdated_skill_paths("shipped")

        self.assertEqual(outdated, [stale])
        self.assertNotIn(current, outdated)

    def test_reports_nothing_when_no_skill_is_installed(self) -> None:
        with patch.object(cloakgpt_skill, "_home_dir", return_value=self.home):
            self.assertEqual(cloakgpt_skill.outdated_skill_paths("shipped"), [])

    def test_reports_nothing_without_a_bundled_skill(self) -> None:
        self._install(".claude", "older")

        with patch.object(cloakgpt_skill, "_home_dir", return_value=self.home):
            self.assertEqual(cloakgpt_skill.outdated_skill_paths(None), [])

    def test_install_command_names_the_official_source(self) -> None:
        self.assertIn(
            "github.com/KoukeNeko/CloakGPT", cloakgpt_skill.install_command_text()
        )
        self.assertIn("skills add", cloakgpt_skill.install_command_text())


if __name__ == "__main__":
    unittest.main()
