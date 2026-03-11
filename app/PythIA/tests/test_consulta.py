from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.usuario import User
from app.consulta import Consulta

class ConsultaModelTest(BaseTestCase):
    def crear_usuario(self):
        u = User(
            nombre ="testuser",
            email="testuser@example.com",
            password_hash="huiawfh"
        )
        db.session.add(u)
        db.session.commit()
        return u

    def test_init_sin_created_at(self):
        u = self.crear_usuario()

        consulta = Consulta(
            user_id=u.id,
            pregunta="¿Caracteristicas de los pliegos administrativos?",
            respuesta="Los pliegos administrativos son...",
            tiempo_respuestas=0.25,
        )
        db.session.add(consulta)
        db.session.commit()
        
        self.assertIsInstance(consulta.created_at, datetime)
        self.assertIsNotNone(consulta.created_at)
        self.assertEqual(consulta.fragmentos, [])

    def test_init_con_created_at(self):
        u = self.crear_usuario()
        fijo = datetime(2020, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        consulta = Consulta(
            user_id=u.id,
            pregunta="¿Caracteristicas de los pliegos administrativos?",
            respuesta="Los pliegos administrativos son...",
            tiempo_respuestas=0.25,
            created_at=fijo,
        )
        db.session.add(consulta)
        db.session.commit()

        fecha = consulta.created_at.replace(tzinfo=None)
        fijo = fijo.replace(tzinfo=None)
        
        self.assertEqual(fecha, fijo)

    def test_campos_obligatorios(self):
        u = self.crear_usuario()

        consulta = Consulta(
            user_id=u.id,
            respuesta="Los pliegos administrativos son...",
            tiempo_respuestas=0.25,
        )

        db.session.add(consulta)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
            
    def test_fk_obligatoria(self):
        consulta = Consulta(
            user_id=None,
            pregunta="¿Caracteristicas de los pliegos administrativos?",
            respuesta="Los pliegos administrativos son...",
            tiempo_respuestas=0.25,
        )
        db.session.add(consulta)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        
    
    def test_relationship_user(self):
        u = self.crear_usuario()

        consulta = Consulta(
            user_id=u.id,
            pregunta="P",
            respuesta="R",
            tiempo_respuestas=0.1,
        )
        db.session.add(consulta)
        db.session.commit()

        self.assertIsNotNone(consulta.user)
        self.assertEqual(consulta.user.id, u.id)

    def test_fragmentos_json(self):
        u = self.crear_usuario()

        consulta = Consulta(
            user_id=u.id,
            pregunta="P",
            respuesta="R",
            fragmentos=[{"ranking": 1, "similitud": 0.99, "metadata": {"filename": "doc.pdf"}}],
            tiempo_respuestas=0.1,
        )
        db.session.add(consulta)
        db.session.commit()

        self.assertEqual(consulta.fragmentos[0]["ranking"], 1)
        self.assertEqual(consulta.fragmentos[0]["metadata"]["filename"], "doc.pdf")
