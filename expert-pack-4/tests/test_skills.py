from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expert_pack.adapters.skills import load_skill_dir, load_skill_directory, parse_frontmatter


class FrontmatterTest(unittest.TestCase):
    def test_block_and_flat_values(self) -> None:
        meta, body = parse_frontmatter(
            "---\nname: demo\ndescription: >\n  a folded\n  description\n---\n# Body\ntext\n"
        )
        self.assertEqual(meta["name"], "demo")
        self.assertEqual(meta["description"], "a folded description")
        self.assertIn("# Body", body)

    def test_missing_frontmatter_keeps_body(self) -> None:
        meta, body = parse_frontmatter("# Just markdown\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "# Just markdown\n")

    def test_unterminated_frontmatter_is_body(self) -> None:
        meta, body = parse_frontmatter("---\nname: x\n")
        self.assertEqual(meta, {})


class SkillDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _skill(self, name: str, body: str, *, module: str | None = None) -> Path:
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(body, encoding="utf-8")
        if module:
            (directory / "skill.py").write_text(module, encoding="utf-8")
        return directory

    def test_prompt_only_skill(self) -> None:
        path = self._skill(
            "manual",
            "---\nname: manual\ndescription: a manual\nwhen_to_use: always\n---\nDo the thing.\n",
        )
        skill = load_skill_dir(path)
        self.assertEqual(skill.spec.name, "manual")
        self.assertEqual(skill.spec.when_to_use, "always")
        result = skill.run(_context(), {})
        self.assertEqual(result.kind, "instructions")
        self.assertIn("Do the thing", result.content)

    def test_executable_skill(self) -> None:
        path = self._skill(
            "runner",
            "---\nname: runner\ndescription: runs code\n---\nmanual text\n",
            module="def run(context, arguments):\n    return {'ok': True, 'content': 'did ' + arguments.get('x','')}\n",
        )
        skill = load_skill_dir(path)
        result = skill.run(_context(), {"x": "it"})
        self.assertIn("did it", result.content)
        self.assertEqual(result.kind, "output")

    def test_executable_skill_exception_becomes_error(self) -> None:
        path = self._skill(
            "boom",
            "---\nname: boom\ndescription: raises\n---\nx\n",
            module="def run(context, arguments):\n    raise RuntimeError('nope')\n",
        )
        skill = load_skill_dir(path)
        result = skill.run(_context(), {})
        self.assertFalse(result.ok)
        self.assertIn("nope", result.error)

    def test_directory_without_manifest_is_skipped(self) -> None:
        (self.root / "nothing").mkdir()
        skills = load_skill_directory(self.root)
        self.assertEqual(skills, [])


def _context():
    from expert_pack.contracts import Observation, SkillContext, State, Task

    return SkillContext(
        task=Task(id="t", goal="g"),
        state=State(key="k", text=""),
        step_index=0,
        observation=Observation("start", ""),
    )


if __name__ == "__main__":
    unittest.main()
