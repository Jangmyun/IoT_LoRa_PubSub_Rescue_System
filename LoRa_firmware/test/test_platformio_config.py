import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlatformIOConfigTests(unittest.TestCase):
    def test_gateway_env_source_exists(self):
        platformio_ini = (ROOT / "platformio.ini").read_text(encoding="utf-8")

        self.assertIn("[env:gateway]", platformio_ini)
        self.assertIn("+<gateway_main.cpp>", platformio_ini)
        self.assertTrue((ROOT / "src" / "gateway_main.cpp").is_file())


if __name__ == "__main__":
    unittest.main()
