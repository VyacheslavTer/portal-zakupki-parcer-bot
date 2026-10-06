import json
import unittest
from pathlib import Path


class ConfigKeywordTests(unittest.TestCase):
    expected_softprom_keywords = {
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
    expected_staffcop_keywords = {
        "StaffCop",
        "Staff Cop",
        "Staffcop",
        "StaffCop Enterprise",
        "StaffCop Standard",
        "StaffCop Lite",
        "StaffCop Agent",
        "Стаффкоп",
        "Стафкоп",
        "Стафф Коп",
        "Стаф Коп",
    }

    def test_example_config_has_softprom_price_list_keywords(self):
        config = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        keywords = set(config["search"]["keywords"])

        self.assertTrue(self.expected_softprom_keywords <= keywords)

    def test_example_config_has_staffcop_keywords(self):
        config = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        keywords = set(config["search"]["keywords"])

        self.assertTrue(self.expected_staffcop_keywords <= keywords)

    def test_erg_example_config_has_softprom_price_list_keywords(self):
        config = json.loads(Path("erg_parser/config.example.json").read_text(encoding="utf-8"))
        keywords = set(config["keywords"])

        self.assertTrue(self.expected_softprom_keywords <= keywords)

    def test_erg_example_config_has_staffcop_keywords(self):
        config = json.loads(Path("erg_parser/config.example.json").read_text(encoding="utf-8"))
        keywords = set(config["keywords"])

        self.assertTrue(self.expected_staffcop_keywords <= keywords)


if __name__ == "__main__":
    unittest.main()
