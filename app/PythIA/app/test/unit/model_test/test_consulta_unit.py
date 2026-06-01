"""
Script con pruebas unitarias del modelo Consulta, encargado de almacenar las preguntas realizadas por los usuarios y las respuestas generadas 
por el sistema RAG. Su objetivo es verificar la correcta creación de consultas, la asociación con los usuarios que las realizan y el almacenamiento 
de información adicional como los fragmentos recuperados y el dispositivo utilizado durante la ejecución
"""

from app.main.code.extensions import db
from app.main.code.model.consulta import Consulta
from app.test.support import BaseAppTestCase


class ConsultaUnitTest(BaseAppTestCase):
    def test_consulta_sets_default_created_at_links_user_and_execution_device(self):
        """
        Verifica que una consulta creada almacena correctamente su fecha de creación, la relación con el usuario y el dispositivo de ejecución utilizado.
        """
        user = self.create_user()
        consulta = Consulta(
            user_id=user.id,
            pregunta="Pregunta",
            respuesta="Respuesta",
            fragmentos=[],
            tiempo_respuestas=0.5,
            execution_device="GPU",
        )
        db.session.add(consulta)
        db.session.commit()

        self.assertIsNotNone(consulta.created_at)
        self.assertEqual(consulta.user.id, user.id)
        self.assertEqual(user.consultas[0].id, consulta.id)
        self.assertEqual(consulta.execution_device, "GPU")

    def test_consulta_preserves_fragmentos_payload(self):
        """
        Comprueba que los fragmentos recuperados durante una consulta se almacenan y recuperan correctamente.
        """
        user = self.create_user()
        fragmentos = [{"ranking": 1, "chunk": "texto"}]
        consulta = Consulta(
            user_id=user.id,
            pregunta="Pregunta",
            respuesta="Respuesta",
            fragmentos=fragmentos,
            tiempo_respuestas=1.2,
        )
        db.session.add(consulta)
        db.session.commit()

        self.assertEqual(consulta.fragmentos, fragmentos)
