"""
Autora: Lydia Blanco Ruiz
Scripts de pruebas unitarias complementarias de los scripts de web scraping, centradas en cubrir ramas 
de ejecución relacionadas con la configuración del entorno, la gestión de directorios y el tratamiento 
de errores durante la inicialización de los módulos.
A diferencia de las pruebas funcionales del web scraping, estas pruebas no ejecutan Playwright ni 
realizan navegación web, sino que verifican el comportamiento de los scripts ante problemas de permisos, 
rutas inexistentes, configuraciones incorrectas y errores producidos durante la carga de los módulos. 
"""

import asyncio
import importlib
import os
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import mock_open, patch


def _reload(module: ModuleType) -> ModuleType:
    """
    Recarga un módulo para aplicar parches a nivel de importación.
    """
    return importlib.reload(module)


class DescargarPliegosUnitTest(unittest.TestCase):
    def test_project_root_falls_back_to_parents(self):
        """
        Verifica que el cálculo del directorio raíz del proyecto utiliza una ruta alternativa cuando no puede 
        localizar la estructura habitual de la aplicación.
        """
        from app.main.code.services.web_scraping import DescargarPliegos as mod

        deep_file = Path(os.getcwd()) / "a" / "b" / "c" / "d" / "e" / "f" / "DescargarPliegos.py"

        with patch("pathlib.Path.resolve", return_value=deep_file), patch("pathlib.Path.is_dir", return_value=False):
            root = mod._project_root()

        self.assertEqual(root, deep_file.parents[5])

    def test_project_root_falls_back_to_app_when_data_missing(self):
        """
        Comprueba que la localización del directorio raíz utiliza el directorio de la aplicación cuando no 
        existe el directorio de datos esperado.
        """
        from app.main.code.services.web_scraping import DescargarPliegos as mod

        def is_dir_side_effect(self: Path) -> bool:
            # Solo existe `.../app`, nunca `.../data`.
            if self.name == "app":
                return True
            if self.name == "data":
                return False
            return False

        with patch("pathlib.Path.is_dir", new=is_dir_side_effect):
            root = mod._project_root()

        self.assertIsInstance(root, Path)

    def test_ensure_dest_dir_falls_back_to_local_pliegos(self):
        """
        Verifica que el directorio de destino para las descargas cambia automáticamente a una ubicación local 
        cuando se producen errores de permisos en la ruta configurada.
        """
        from app.main.code.services.web_scraping import DescargarPliegos as mod

        abs_path = Path(os.getcwd()) / "ABS"
        with patch.dict("os.environ", {"DOCS_DIR": str(abs_path)}, clear=False), patch.object(
            mod, "DEST", abs_path
        ):
            with patch.object(Path, "mkdir", side_effect=[PermissionError, None]):
                mod.ensure_dest_dir()
            self.assertEqual(mod.DEST, Path("pliegos"))

    def test_ensure_dest_dir_raises_when_permission_error(self):
        """
        Comprueba que se genera una excepción cuando no es posible crear el directorio de destino y 
        no existe una ubicación alternativa válida.
        """
        from app.main.code.services.web_scraping import DescargarPliegos as mod

        with patch.dict("os.environ", {"DOCS_DIR": "rel"}, clear=False), patch.object(
            mod, "DEST", Path("rel")
        ), patch.object(Path, "mkdir", side_effect=PermissionError), self.assertRaises(PermissionError):
            mod.ensure_dest_dir()

    def test_run_raises_file_not_found_when_no_json(self):
        """
        Verifica que el proceso de descarga se interrumpe correctamente cuando falta el fichero JSON de entrada necesario para la ejecución.
        """
        from app.main.code.services.web_scraping import DescargarPliegos as mod

        with patch.object(mod, "RUTA_JSON", Path("__missing__.json")
        ),self.assertRaises(FileNotFoundError):
            asyncio.run(mod.run())

    def test_import_time_chmod_and_unlink_oserror_are_ignored(self):
        """
        Comprueba que determinados errores de permisos y eliminación de archivos producidos durante la carga del módulo son gestionados sin interrumpir 
        la inicialización en sistemas POSIX.
        """
        import sys

        module_path = Path("app/main/code/services/web_scraping/DescargarPliegos.py").resolve()
        fake_os = ModuleType("os")
        fake_os.name = "posix"
        fake_os.environ = os.environ

        prev_os = sys.modules.get("os")
        sys.modules["os"] = fake_os
        try:
            with patch("pathlib.Path.mkdir", return_value=None), patch(
                "pathlib.Path.chmod", side_effect=OSError
            ), patch("pathlib.Path.open", mock_open()), patch("pathlib.Path.unlink", side_effect=OSError):
                import importlib.util

                module_name = "DescargarPliegos_test_exec"
                spec = importlib.util.spec_from_file_location(module_name, str(module_path))
                module = importlib.util.module_from_spec(spec)
                module.__file__ = str(module_path)
                try:
                    spec.loader.exec_module(module) 
                finally:
                    try:
                        del __import__("sys").modules[module_name]
                    except KeyError:
                        pass
        finally:
            if prev_os is None:
                del sys.modules["os"]
            else:
                sys.modules["os"] = prev_os


class PliegosPlaywrightAsincronoUnitTest(unittest.TestCase):
    def test_project_root_falls_back_to_parents(self):
        """
        Verifica que el cálculo del directorio raíz del proyecto utiliza rutas alternativas cuando no se localiza 
        la estructura habitual de la aplicación.
        """
        from app.main.code.services.web_scraping import (
            PliegosPlaywrightAsincrono as mod,
        )

        deep_file = Path(os.getcwd()) / "a" / "b" / "c" / "d" / "e" / "f" / "PliegosPlaywrightAsincrono.py"

        with patch("pathlib.Path.resolve", return_value=deep_file), patch("pathlib.Path.is_dir", return_value=False):
            root = mod._project_root()

        self.assertEqual(root, deep_file.parents[5])

    def test_project_root_falls_back_to_app_dir(self):
        """
        Comprueba que el módulo localiza correctamente el directorio raíz utilizando la carpeta de la aplicación cuando 
        faltan directorios auxiliares.
        """
        from app.main.code.services.web_scraping import (
            PliegosPlaywrightAsincrono as mod,
        )

        def is_dir_side_effect(self: Path) -> bool:
            """
            Construye una estructura de directorios donde solo existe .../app.
            """
            if self.name == "app":
                return True
            if self.name == "data":
                return False
            return False

        with patch("pathlib.Path.is_dir", new=is_dir_side_effect):
            root = mod._project_root()
        self.assertIsInstance(root, Path)

    def test_ensure_writable_dir_ignores_chmod_and_unlink_errors_in_posix(self):
        """
        Verifica que los errores producidos al modificar permisos o eliminar archivos temporales no impiden la preparación de directorios 
        de trabajo en sistemas POSIX.
        """
        from app.main.code.services.web_scraping import (
            PliegosPlaywrightAsincrono as mod,
        )

        tmp = Path(os.getcwd()) / "data" / "web_scraping_test_tmp"
        with patch.object(mod.os, "name", "posix"), patch("pathlib.Path.chmod", side_effect=OSError), patch(
            "pathlib.Path.unlink", side_effect=OSError
        ):
            mod._ensure_writable_dir(tmp)

    def test_import_raises_runtime_error_when_output_dir_not_writable(self):
        """
        Comprueba que la inicialización del módulo genera una excepción cuando el directorio de salida no dispone
        de permisos de escritura suficientes
        """
        import importlib
        import sys
        import types

        # Evita depender de Playwright real en CI instalando stubs mínimos.
        if "playwright.async_api" not in sys.modules:
            async_api = types.ModuleType("playwright.async_api")
            async_api.Error = RuntimeError
            async_api.TimeoutError = TimeoutError
            async_api.Frame = object
            async_api.Locator = object
            async_api.Page = object
            async_api.async_playwright = lambda: None
            async_api.expect = lambda *args, **kwargs: None
            sys.modules["playwright.async_api"] = async_api
        if "playwright" not in sys.modules:
            sys.modules["playwright"] = types.ModuleType("playwright")

        with patch("pathlib.Path.mkdir", side_effect=OSError("nope")):
            sys.modules.pop("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono", None)
            with self.assertRaises(RuntimeError) as raised:
                importlib.import_module("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono")
        self.assertIn("No hay permisos de escritura", str(raised.exception))
