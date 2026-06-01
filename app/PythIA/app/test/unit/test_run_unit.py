"""
Autora: Lydia Blanco Ruiz
Script con pruebas del punto de entrada WSGI. Su objetivo es verificar que, al ejecutar el módulo principal, 
se crea correctamente la instancia de la aplicación Flask mediante la factoría create_app, se inicia el servidor 
con la configuración esperada y se expone adecuadamente la aplicación para su ejecución. Estas pruebas garantizan 
el correcto funcionamiento del mecanismo de arranque de la aplicación.
"""

import runpy
import unittest
from unittest.mock import MagicMock, patch


class RunModuleUnitTest(unittest.TestCase):
    def test_run_module_creates_app_and_runs_when_main(self):
        """
        Verifica que la ejecución directa del módulo principal crea correctamente la aplicación Flask, inicia 
        el servidor con la configuración prevista y expone la instancia de la aplicación para su uso por el entorno WSGI.
        """
        fake_app = MagicMock()

        with patch("app.main.code.create_app", return_value=fake_app) as mock_create_app:
            module_globals = runpy.run_module("app.main.code.run", run_name="__main__")

        mock_create_app.assert_called_once_with()
        fake_app.run.assert_called_once_with(host="0.0.0.0", port=5000)
        self.assertIs(module_globals["app"], fake_app)
