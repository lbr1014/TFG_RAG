"""
Autora: Lydia Blanco Ruiz
Pruebas unitarias para la lógica de evaluación RAG (RAGAS + coseno).
"""

import math
from unittest.mock import patch

from app.test.support import BaseAppTestCase


class _FakeEmbeddings:
    def embed_documents(self, texts):
        vectors = []
        for text in texts:
            text = text or ""
            length = float(len(text))
            vowels = float(sum(text.lower().count(v) for v in "aeiouáéíóú"))
            vectors.append([length, vowels, 1.0])
        return vectors


class EvaluacionRAGASUnitTest(BaseAppTestCase):
    def _module(self):
        # Importa siempre con el stub de PrototipoRAG ya instalado por app.test.support.
        from app.main.code.services.evaluation import evaluacion_RAGAS

        return evaluacion_RAGAS

    def test_normalize_base_url_adds_scheme_and_rejects_insecure_remote_http(self):
        m = self._module()

        self.assertEqual(m._normalize_base_url(""), "")
        self.assertEqual(m._normalize_base_url("localhost:11434"), "http://localhost:11434")
        self.assertEqual(m._normalize_base_url("127.0.0.1:11434/"), "http://127.0.0.1:11434")
        self.assertEqual(m._normalize_base_url("ollama:11434"), "http://ollama:11434")
        self.assertEqual(m._normalize_base_url("example.com:11434"), "https://example.com:11434")
        with self.assertRaises(ValueError):
            m._normalize_base_url("http://example.com:11434")

    def test_combine_scores_weighted_and_fallback(self):
        m = self._module()

        with patch.object(m, "FINAL_RAGAS_WEIGHT", 0.7), patch.object(m, "FINAL_FALLBACK_WEIGHT", 0.3):
            self.assertAlmostEqual(m.combine_scores(0.8, 0.2), 0.62, places=6)
            self.assertEqual(m.combine_scores(0.9, None), 0.9)
            self.assertEqual(m.combine_scores(None, 0.1), 0.1)
            self.assertIsNone(m.combine_scores(None, None))

        with patch.object(m, "FINAL_RAGAS_WEIGHT", 0.0), patch.object(m, "FINAL_FALLBACK_WEIGHT", 0.0):
            # Peso total inválido: conserva RAGAS cuando existe.
            self.assertEqual(m.combine_scores(0.25, 0.75), 0.25)

    def test_summarize_metric_values_ignores_nones_and_nans(self):
        m = self._module()

        rows = [
            {"ragas_metrics": {"faithfulness": 0.5, "answer_relevancy": None}},
            {"ragas_metrics": {"faithfulness": float("nan"), "answer_relevancy": 1.0}},
            {"ragas_metrics": {"faithfulness": 0.75, "answer_relevancy": 0.0}},
        ]

        with patch.object(m, "selected_metric_names", return_value=["faithfulness", "answer_relevancy"]):
            summary = m.summarize_metric_values(rows, "ragas_metrics")

        self.assertAlmostEqual(summary["faithfulness"], 0.625, places=6)
        self.assertAlmostEqual(summary["answer_relevancy"], 0.5, places=6)

    def test_build_source_counts_unknown_source_maps_to_missing(self):
        m = self._module()

        rows = [
            {"score_source": {"faithfulness": "weighted", "answer_relevancy": "ragas"}},
            {"score_source": {"faithfulness": "coseno", "answer_relevancy": "algo-raro"}},
            {"score_source": {}},
        ]

        with patch.object(m, "selected_metric_names", return_value=["faithfulness", "answer_relevancy"]):
            counts = m.build_source_counts(rows)

        self.assertEqual(counts["faithfulness"], {"weighted": 1, "ragas": 0, "coseno": 1, "missing": 1})
        self.assertEqual(counts["answer_relevancy"], {"weighted": 0, "ragas": 1, "coseno": 0, "missing": 2})

    def test_compute_coseno_metrics_populates_expected_fields(self):
        m = self._module()
        embeddings = _FakeEmbeddings()

        rows = [
            {
                "question": "¿Qué es X?",
                "answer": "X es una cosa.",
                "ground_truth": "X es una cosa.",
                "evidence": "X es una cosa.",
                "contexts": ["X es una cosa.", "Texto distinto."],
            }
        ]

        out = m.compute_coseno_metrics(rows, embeddings)
        metrics = out[0]["_coseno_metrics"]

        self.assertIn("faithfulness", metrics)
        self.assertIn("answer_relevancy", metrics)
        self.assertIn("answer_correctness", metrics)
        self.assertIn("context_precision", metrics)
        self.assertIn("context_recall", metrics)
        self.assertIn("context_relevancy", metrics)

        for value in metrics.values():
            if value is None:
                continue
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
            self.assertFalse(math.isnan(value))

    def test_merge_metrics_combines_ragas_and_coseno_and_tracks_source(self):
        m = self._module()

        rows = [
            {
                "question": "Q1",
                "contexts": ["c1"],
                "answer": "a1",
                "ground_truth": "g1",
                "evidence": "e1",
                "_coseno_metrics": {"faithfulness": 0.25, "answer_relevancy": 0.5},
            },
            {
                "question": "Q2",
                "contexts": [],
                "answer": "a2",
                "_coseno_metrics": {"faithfulness": 0.9, "answer_relevancy": 0.1},
            },
        ]
        ragas_rows = [{"question": "Q1", "faithfulness": 0.75}]

        with patch.object(m, "selected_metric_names", return_value=["faithfulness", "answer_relevancy"]), patch.object(
            m, "FINAL_RAGAS_WEIGHT", 1.0
        ), patch.object(m, "FINAL_FALLBACK_WEIGHT", 1.0):
            summary, final_rows = m.merge_metrics(rows, ragas_rows)

        self.assertEqual(len(final_rows), 2)
        q1 = next(item for item in final_rows if item["question"] == "Q1")
        q2 = next(item for item in final_rows if item["question"] == "Q2")

        self.assertEqual(q1["score_source"]["faithfulness"], "weighted")
        self.assertEqual(q2["score_source"]["faithfulness"], "coseno")
        self.assertEqual(q1["ragas_metrics"]["faithfulness"], 0.75)
        self.assertEqual(q1["coseno_metrics"]["faithfulness"], 0.25)
        self.assertIsNone(q2["ragas_metrics"]["faithfulness"])

        self.assertIn("faithfulness", summary)
        self.assertIn("answer_relevancy", summary)

    def test_load_questions_normalizes_string_items(self):
        m = self._module()
        path = self._tmpdir / "q.json"
        path.write_text("[{\"question\": \"uno\"}, \"dos\"]", encoding="utf-8")

        questions = m.load_questions(path)
        self.assertEqual(questions[0]["question"], "uno")
        self.assertEqual(questions[1]["question"], "dos")
