import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_demo


class DemoLogicTests(unittest.TestCase):
    def test_guess_metadata_for_rag_document(self):
        result = web_demo.guess_metadata("huong_dan_rag.md", "Quy trình embedding và retrieval")
        self.assertEqual(result["topic"], "Trí tuệ nhân tạo")
        self.assertEqual(result["doc_type"], "Quy trình")

    def test_visible_documents_respects_private_access(self):
        state = web_demo.seed_state()
        lecturer_docs = web_demo.visible_documents(state, "GV001")
        self.assertNotIn("doc-exam-process", {doc["id"] for doc in lecturer_docs})
        head_docs = web_demo.visible_documents(state, "TBM01")
        self.assertIn("doc-exam-process", {doc["id"] for doc in head_docs})

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            with patch.object(web_demo, "DATA_DIR", Path(directory)), patch.object(web_demo, "STATE_FILE", state_file):
                expected = web_demo.seed_state()
                web_demo.save_state(expected)
                self.assertEqual(web_demo.load_state()["documents"][0]["id"], "doc-de-cuong-ai")


if __name__ == "__main__":
    unittest.main()
