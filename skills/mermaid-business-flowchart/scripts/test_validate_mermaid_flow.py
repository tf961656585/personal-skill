import tempfile
import unittest
from pathlib import Path

from validate_mermaid_flow import load_mermaid_text, validate_mermaid_text


class ValidateMermaidFlowTests(unittest.TestCase):
    def test_valid_flowchart_passes(self):
        text = """flowchart TD
        A([开始]) --> B{校验参数}
        B -- 通过 --> C[创建订单]
        B -- 拒绝 --> D[提示错误]
        C --> E([结束-成功])
        D --> F([结束-失败])
        """
        self.assertEqual(validate_mermaid_text(text), [])

    def test_non_flowchart_type_fails(self):
        text = """sequenceDiagram
        participant U as User
        U->>S: hello
        """
        errors = validate_mermaid_text(text)
        self.assertTrue(any("仅允许 Mermaid flowchart/graph" in e for e in errors))

    def test_decision_requires_two_outgoing_edges(self):
        text = """flowchart TD
        A --> B{是否通过}
        B -- 是 --> C
        """
        errors = validate_mermaid_text(text)
        self.assertTrue(any("出口少于 2 条" in e for e in errors))

    def test_markdown_mermaid_block_extraction(self):
        markdown = """# 标题

```mermaid
flowchart TD
A --> B
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "demo.md"
            path.write_text(markdown, encoding="utf-8")
            self.assertEqual(load_mermaid_text(path), "flowchart TD\nA --> B")

    def test_unquoted_risky_punctuation_in_label_fails(self):
        text = """flowchart TD
        A --> B[updateNodeMeasuredBatch via reactflow:onNodesChange(dimensions)]
        B --> C
        """
        errors = validate_mermaid_text(text)
        self.assertTrue(any("高风险标点" in e for e in errors))

    def test_quoted_risky_punctuation_in_label_passes(self):
        text = """flowchart TD
        A --> B["updateNodeMeasuredBatch via reactflow:onNodesChange(dimensions)"]
        B --> C
        """
        self.assertEqual(validate_mermaid_text(text), [])


if __name__ == "__main__":
    unittest.main()
