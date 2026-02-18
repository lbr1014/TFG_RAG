import unittest
from unittest.mock import patch

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.usuario import User

class RagRoutesTest(BaseTestCase):
    def login_ok(self):
        self.user = self.crear_usuario(email="u1@example.com", password="pw123456", is_admin=False)
        return self.client.post(
            "/login",
            data={"email": "u1@example.com", "password": "pw123456"},
            follow_redirects=False,
        )
    
    def test_requires_login(self):
        resp = self.client.get("/rag/", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 401))
        if resp.status_code == 302:
            self.assertIn("/login", resp.headers.get("Location", ""))
            
        resp = self.client.post("/rag/ask", data={"question": "hola"}, follow_redirects=False)
        self.assertIn(resp.status_code, (302, 401))
        if resp.status_code == 302:
            self.assertIn("/login", resp.headers.get("Location", ""))
    
    def test_login_correcto(self):
        self.login_ok()
        resp = self.client.get("/rag/", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data)
        
    def test_rag_fail(self):
        self.login_ok()
        resp = self.client.post("/rag/ask", data={"question": ""}, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)

        data = resp.get_json()
        self.assertEqual(data["answer"], "Escribe una pregunta válida.")
        self.assertEqual(data["title"], "")
        self.assertEqual(data["filename"], "")
        self.assertEqual(data["segment_index"], -1)
        self.assertEqual(data["chunk"], "")
        
    def test_rag_correcto(self):
        self.login_ok()

        fake = {
            "answer": "ok",
            "title": "t",
            "filename": "f.pdf",
            "segment_index": 3,
            "chunk": "texto",
            "elapsed_s": 0.1,
            "qdrant_point_id": "abc",
        }
        
        with patch("app.rag.routes.rag_answer", return_value=fake) as mock_rag:
            resp = self.client.post("/rag/ask", data={"question": "hola"}, follow_redirects=False)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["answer"], "ok")
        self.assertEqual(data["filename"], "f.pdf")
        mock_rag.assert_called_once_with("hola")
        
    