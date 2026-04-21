from tests.support import BaseAppTestCase

from app.entities.consulta import Consulta
from app.extensions import db


class ConsultaUnitTest(BaseAppTestCase):
    def test_consulta_sets_default_created_at_and_links_user(self):
        user = self.create_user()
        consulta = Consulta(
            user_id=user.id,
            pregunta="Pregunta",
            respuesta="Respuesta",
            fragmentos=[],
            tiempo_respuestas=0.5,
        )
        db.session.add(consulta)
        db.session.commit()

        self.assertIsNotNone(consulta.created_at)
        self.assertEqual(consulta.user.id, user.id)
        self.assertEqual(user.consultas[0].id, consulta.id)

    def test_consulta_preserves_fragmentos_payload(self):
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
