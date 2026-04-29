"""
Autora: Lydia Blanco Ruiz
Script con pruebas del punto de entrada WSGI.
"""

import runpy
import unittest
from unittest.mock import MagicMock, patch


class RunModuleUnitTest(unittest.TestCase):
    def test_run_module_creates_app_and_runs_when_main(self):
        fake_app = MagicMock()

        with patch("app.main.code.create_app", return_value=fake_app) as mock_create_app:
            module_globals = runpy.run_module("app.main.code.run", run_name="__main__")

        mock_create_app.assert_called_once_with()
        fake_app.run.assert_called_once_with(host="0.0.0.0", port=5000)
        self.assertIs(module_globals["app"], fake_app)
