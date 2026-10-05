import json
import unittest
from pathlib import Path


class ConfigKeywordTests(unittest.TestCase):
    def test_example_config_has_softprom_price_list_keywords(self):
        config = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        keywords = set(config["search"]["keywords"])

        expected = {
            "Google Workspace",
            "Google Workspaces",
            "G Suite",
            "Corel",
            "CorelDRAW",
            "Corel Draw",
            "Alludo",
            "WinZip",
            "MindManager",
            "Mind Manager",
            "Parallels",
            "Parallels Desktop",
            "Roxio",
            "PaintShop",
            "Painter",
            "VideoStudio",
            "Pinnacle",
            "AfterShot",
            "ParticleShop",
            "Sefaira",
            "V-Ray",
            "Trimble Connect",
            "VNZ",
        }

        self.assertTrue(expected <= keywords)


if __name__ == "__main__":
    unittest.main()
