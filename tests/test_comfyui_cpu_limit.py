import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "docker/comfyui/run-cpu-limited.py"
SPEC = importlib.util.spec_from_file_location("run_cpu_limited", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComfyUiCpuLimitTests(unittest.TestCase):
    def test_uses_percentage_of_detected_allowed_cores(self):
        selected = []

        def _capture_affinity(_pid, cores):
            selected.append(set(cores))

        with (
            patch.dict(os.environ, {"HEXE_COMFYUI_CPU_CORE_LIMIT_PERCENT": "50"}, clear=False),
            patch.object(MODULE.os, "sched_getaffinity", return_value=set(range(7))),
            patch.object(MODULE.os, "sched_setaffinity", side_effect=_capture_affinity),
            patch.object(MODULE.os, "execvp", side_effect=RuntimeError("exec")),
            patch.object(MODULE.sys, "argv", [str(SCRIPT_PATH), "python3", "main.py"]),
        ):
            os.environ.pop("OMP_NUM_THREADS", None)
            os.environ.pop("MKL_NUM_THREADS", None)
            with self.assertRaisesRegex(RuntimeError, "exec"):
                MODULE.main()

            self.assertEqual(os.environ["OMP_NUM_THREADS"], "4")
            self.assertEqual(os.environ["MKL_NUM_THREADS"], "4")

        self.assertEqual(selected, [{0, 1, 2, 3}])


if __name__ == "__main__":
    unittest.main()
