import json
import tempfile
import unittest
from pathlib import Path

from rag_pipeline import answer_question, load_documents, run_pipeline
from validate import validate_artifacts


class PipelineIntegrationTest(unittest.TestCase):
    def test_replacement_fixtures_replay_without_filename_assumptions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb").mkdir()
            (root / "kb" / "renamed-guide.md").write_text(
                "Title: Shipping timetable\r\nSection: Orders\r\n\r\nStandard delivery takes 5 business days.\r\nExpress delivery takes 2 business days.\r\n",
                encoding="utf-8", newline="")
            (root / "kb" / "other.txt").write_text(
                "Title: Returns\nSection: Orders\n\nReturns are accepted within 30 days.\n", encoding="utf-8")
            (root / "kb" / "fallback.markdown").write_text("Contact support for order changes.\n", encoding="utf-8")
            (root / "kb" / "empty.txt").write_text("", encoding="utf-8")
            (root / "queries.json").write_text(json.dumps([
                {"query_id": "shipping", "question": "How long does express delivery take?", "expected_doc_titles": ["Shipping timetable"]},
                {"query_id": "returns", "question": "What is the return window?", "expected_doc_titles": ["Returns"]},
            ]), encoding="utf-8")
            result = run_pipeline(root)
            self.assertTrue(result["manifest"]["validation"]["passed"])
            self.assertEqual(result["evaluation"]["summary"]["hits"], 2)
            self.assertEqual(validate_artifacts(root)["checked_queries"], 2)
            shipping_answer = answer_question(root, "How long does express delivery take?")
            self.assertIn("Express delivery takes 2 business days", shipping_answer["answer"])
            self.assertTrue(any("empty file" in warning for warning in result["manifest"]["warnings"]))
            chunks = json.loads((root / "artifacts/chunks.json").read_text())
            docs, _ = load_documents(root)
            sources = {doc.path: doc.source for doc in docs}
            for chunk in chunks:
                self.assertEqual(chunk["text"], sources[chunk["source_path"]][chunk["start_char"]:chunk["end_char"]])
            unknown = answer_question(root, "What is the lunar office dress code?")
            self.assertEqual(unknown["answer_label"], "insufficient_context")
            weak_overlap = answer_question(root, "How can I protect my order account?")
            self.assertEqual(weak_overlap["answer_label"], "insufficient_context")
            keyword = answer_question(root, "delivery")
            self.assertEqual(keyword["answer_label"], "insufficient_context")
            self.assertEqual(keyword["answer_reason"], "underspecified_question")
            self.assertIn("more specific question", keyword["answer"])
            absent_keyword = answer_question(root, "quasarxyz")
            self.assertEqual(absent_keyword["answer_reason"], "no_matching_evidence")
            topic = answer_question(root, "Shipping timetable")
            self.assertEqual(topic["answer_label"], "grounded_answer")
            self.assertEqual(topic["answer_reason"], "topic_overview")
            self.assertIn("Standard delivery takes 5 business days", topic["answer"])


if __name__ == "__main__":
    unittest.main()
