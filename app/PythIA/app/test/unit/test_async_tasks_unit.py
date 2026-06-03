import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


class AsyncTasksShutdownUnitTest(unittest.TestCase):
    def _load_async_tasks_module(self):
        module_path = (
            Path(__file__).resolve().parents[2]
            / "main"
            / "code"
            / "services"
            / "async_tasks.py"
        )
        spec = importlib.util.spec_from_file_location("async_tasks_testshim", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module

    def test_register_executor_shutdown_registers_atexit(self):
        async_tasks = self._load_async_tasks_module()
        async_tasks._shutdown_done = False
        with patch.object(async_tasks.atexit, "register") as mock_register:
            async_tasks.register_executor_shutdown(app=None)
        mock_register.assert_called()

    def test_shutdown_executors_is_idempotent(self):
        async_tasks = self._load_async_tasks_module()
        async_tasks._shutdown_done = False
        with patch.object(async_tasks.executor, "shutdown") as rag_shutdown, patch.object(
            async_tasks.markdown_executor, "shutdown"
        ) as md_shutdown:
            async_tasks.shutdown_executors()
            async_tasks.shutdown_executors()
        self.assertEqual(rag_shutdown.call_count, 1)
        self.assertEqual(md_shutdown.call_count, 1)
