from tests.__init__ import BaseTestCase
from unittest.mock import patch
from app.extensions import db
from app.usuario import User
from app.consulta import Consulta
from app.chunk import Chunk
from app.documentos import Documento
from app.consultaChunk import ConsultaChunk

class MainRoutesTest(BaseTestCase):
    
    def cleanup_for_user_delete(self):
        db.session.query(ConsultaChunk).delete(synchronize_session=False)
        db.session.query(Consulta).delete(synchronize_session=False)
        db.session.query(Chunk).delete(synchronize_session=False)
        db.session.query(Documento).delete(synchronize_session=False)
        db.session.commit()


    def test_pag_principal_correcto(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_pag_login_correcto(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)

    def test_edit_user_actualiza_nombre_y_email(self):
        u = self.crear_usuario()
        self.login()

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "Nuevo Nombre",
                "email": "nuevonombre@example.com",
                "submit": "Guardar cambios",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u)
        self.assertEqual(u.nombre, "Nuevo Nombre")
        self.assertEqual(u.email, "nuevonombre@example.com")
        
    def test_edit_user_no_borra_campos_vacios(self):
        u = self.crear_usuario(nombre="Nombre Original", email="original@example.com")
        self.login(email="original@example.com")

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "",         
                "email": "",         
                "new_password": "",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u)
        self.assertEqual(u.nombre, "Nombre Original")
        self.assertEqual(u.email, "original@example.com")
        
    def test_edit_user_cambia_password(self):
        u = self.crear_usuario(password="oldpass")
        self.login(password="oldpass")

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "Test",               
                "email": "test@example.com",    
                "new_password": "newpass123",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u)
        self.assertTrue(u.check_password("newpass123"))
        
    def test_edit_user_email_duplicado(self):
        u1 = self.crear_usuario(nombre="U1", email="u1@example.com", password="123456")
        self.crear_usuario(nombre="U2", email="u2@example.com", password="123456")

        # login como u1 e intenta poner el email de u2
        self.login(email="u1@example.com", password="123456", follow_redirects=True)

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "U1",
                "email": "u2@example.com", 
                "new_password": "",
                "submit": "Guardar cambios",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u1)
        self.assertEqual(u1.email, "u1@example.com")  
        
        self.assertIn(b"Ya existe un usuario con ese email.", r.data)
        
    def test_edit_user_precarga_datos(self):
        self.crear_usuario(nombre="Alexia", email="alexia@gmail.com", password="123456")
        self.login(email="alexia@gmail.com", password="123456", follow_redirects=True)

        r = self.client.get("/edit_user")
        self.assertEqual(r.status_code, 200)

        self.assertIn(b'value="Alexia"', r.data)
        self.assertIn(b'value="alexia@gmail.com"', r.data)

    def crear_consulta(self, user_id: int, pregunta="Pregunta", respuesta="Respuesta"):
        consulta = Consulta(
            user_id=int(user_id),
            pregunta=pregunta,
            respuesta=respuesta,
            tiempo_respuestas=0.25,
        )
        db.session.add(consulta)
        db.session.commit()
        return consulta
    
    def crear_documento(self):
        doc = Documento(
           nombre="doc1",
           path = "el_path_del _documento.pdf",
           size_bytes = 2024,
           modified_at = None,
           chunks = 5,
           hash = "200",
           status = "cargado",
           error_message = None
        )
        db.session.add(doc)
        db.session.commit()
        return doc
    
    def crear_chunk(self, segment_index=0, doc_sha256="h"):
        doc = self.crear_documento()
        chunk = Chunk(
            document_id=doc.id,
            qdrant_point_id="qid-1",
            segment_index=segment_index,
            doc_sha256=doc_sha256,
            n_chars=10,
            n_tokens=3,
        )
        db.session.add(chunk)
        db.session.commit()
        return chunk
    
    @patch("app.main.routes.qdrant_get_payloads", return_value={})
    def test_history_paginacion(self, _mock_qdrant):
        u = self.crear_usuario(email="u_hist_1@example.com")
        self.login(email="u_hist_1@example.com")
        self.crear_consulta(user_id=u.id)

        r = self.client.get("/history?page=0")
        self.assertEqual(r.status_code, 200)
        
        u = self.crear_usuario(email="u_hist_2@example.com")
        self.login(email="u_hist_2@example.com")
        self.crear_consulta(user_id=u.id)

        r = self.client.get("/history?page=999")
        self.assertEqual(r.status_code, 200)
        
        self.cleanup_for_user_delete()
    
    def test_history(self):
        u = self.crear_usuario(email="u_hist_3@example.com")
        self.login(email="u_hist_3@example.com")

        self.crear_consulta(user_id=u.id, pregunta="sin chunks", respuesta="ok")
        c2 = self.crear_consulta(user_id=u.id, pregunta="con chunk", respuesta="ok")
        ch = self.crear_chunk()

        cc = ConsultaChunk(
            consulta_id=int(c2.id),
            chunk_id=int(ch.id),
            similitud=0.9,
            ranking=1,
        )
        db.session.add(cc)
        db.session.commit()

        fake_payloads = {
            "qid-1": {
                "metadata": {"filename": "doc_meta.pdf", "title": "T"},
                "content": "contenido",
            }
        }

        with patch("app.main.routes.qdrant_get_payloads", return_value=fake_payloads) as m:
            r = self.client.get("/history?page=1")
            self.assertEqual(r.status_code, 200)

            called_args = m.call_args[0][0]  
            self.assertIn("qid-1", list(called_args))
        
        self.cleanup_for_user_delete()

    def test_delete_consulta_incorrecto(self):
        owner = self.crear_usuario(email="owner@example.com")
        self.crear_usuario(email="other@example.com")

        c = self.crear_consulta(user_id=owner.id, pregunta="p", respuesta="r")

        self.login(email="other@example.com")
        r = self.client.post(f"/consulta/{c.id}/delete")
        self.assertEqual(r.status_code, 403)
        
        self.cleanup_for_user_delete()
        
    def test_delete_consulta_correcta(self):
        owner = self.crear_usuario(email="owner2@example.com")
        self.login(email="owner2@example.com")

        c = self.crear_consulta(user_id=owner.id, pregunta="p", respuesta="r")
        cid = int(c.id)

        r = self.client.post(f"/consulta/{cid}/delete", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/history"))

        self.assertIsNone(Consulta.query.get(cid))