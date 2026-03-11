import unittest
import tempfile

from ai_node.main import run


class MainEntrypointTests(unittest.TestCase):
    def test_run_once_returns_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                log_file=f"{tmp}/backend.log",
            )
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
