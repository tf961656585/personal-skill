import re
import unittest
from pathlib import Path


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.skill_root = Path(__file__).resolve().parent.parent

    def test_skill_frontmatter_contains_required_fields(self):
        content = (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        self.assertIn("name: mermaid-business-flowchart", content)
        self.assertIn("description:", content)
        self.assertIn("仅使用 Mermaid", content)

    def test_skill_enforces_confirmation_before_save(self):
        content = (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("未收到用户明确保存确认前，不写入仓库文件。", content)

    def test_skill_requires_quoted_labels_for_risky_punctuation(self):
        content = (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("节点文案若包含 `: () [] {} |` 任一字符，必须使用双引号包裹", content)

    def test_required_references_exist(self):
        self.assertTrue((self.skill_root / "references" / "flowchart-standard-v2.md").exists())
        self.assertTrue((self.skill_root / "references" / "templates.md").exists())

    def test_openai_yaml_has_required_interface_keys(self):
        content = (self.skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("interface:\n"), "缺少 interface 根键")
        for key in ("display_name", "short_description", "default_prompt"):
            pattern = re.compile(rf"^\s+{re.escape(key)}:\s+\".+\"$", re.MULTILINE)
            self.assertRegex(content, pattern)


if __name__ == "__main__":
    unittest.main()
