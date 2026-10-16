import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from studio.domain import COLORS, composition_text, import_column_c, parse_composition, validate_composition
from studio.storage import Store, StorageError, default_data_dir


class CompositionTests(unittest.TestCase):
    def test_chinese_adjacent_parts_and_aliases(self):
        parts = parse_composition("棉10%亚麻30%聚酯纤维30%粘纤30%")
        self.assertEqual(parts, [{"name": "Cotton", "percent": 10.0}, {"name": "Linen", "percent": 30.0}, {"name": "Polyester", "percent": 30.0}, {"name": "Viscose", "percent": 30.0}])
        self.assertEqual(composition_text(parts), "10% Cotton\n30% Linen\n30% Polyester\n30% Viscose")

    def test_english_and_full_width_percent(self):
        self.assertEqual(parse_composition("95.5% cotton, 4.5％ SPANDEX"), [{"name": "Cotton", "percent": 95.5}, {"name": "Elastane", "percent": 4.5}])
        self.assertEqual(composition_text(parse_composition("polyester fibre: 100%")), "100% Polyester")

    def test_invalid_text_is_not_partially_imported(self):
        for value in ["Cotton 100% mystery", "Cottonwood100%", "100% Cottonwood", "羊驼绒100%", "棉90%", "棉0%亚麻100%", "棉-10%亚麻110%", "100%", "", "棉50%棉50%"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_composition(value)

    def test_total_tolerance_and_nonfinite_rejection(self):
        self.assertEqual(len(parse_composition("33.33% Cotton 33.33% Linen 33.33% Wool")), 3)
        for value in ["nan", "inf", True, None, -1, 101]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_composition([{"name": "Cotton", "percent": value}])

    def test_twelve_unique_colors(self):
        self.assertEqual(len(COLORS), 12)
        self.assertEqual(len({color["id"] for color in COLORS}), 12)


class ImportTests(unittest.TestCase):
    def test_column_c_and_bad_rows(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "composition.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "成分"
            sheet["C3"] = "成分"
            sheet["C4"] = "棉100%"
            sheet["C6"] = "未识别100%"
            sheet["C7"] = "棉20%聚酯纤维80%"
            sheet["C8"] = '=CONCAT("棉", "100%")'
            sheet["D4"] = "羊毛100%"
            workbook.create_sheet("Other")["C1"] = "100% Silk"
            workbook.save(path)
            workbook.close()
            result = import_column_c(path)
            self.assertEqual(len(result["compositions"]), 2)
            self.assertEqual(result["compositions"][0]["raw"], "棉100%")
            self.assertEqual(result["compositions"][0]["source"], "成分!C4")
            self.assertEqual([item["row"] for item in result["errors"]], [6, 8])
            self.assertEqual(result["sheets"], ["成分", "Other"])
            self.assertEqual(import_column_c(path, "Other")["compositions"][0]["parts"][0]["name"], "Silk")
            with self.assertRaises(ValueError):
                import_column_c(path, "missing")


class StorageTests(unittest.TestCase):
    def test_defaults_round_trip_jobs_and_no_plaintext(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            settings = store.load_settings()
            self.assertEqual(settings["concurrency"], 2)
            settings["api_key"] = "test-secret-must-not-be-saved"
            with patch("studio.storage._protect_key", return_value="dpapi:v1:ciphertext"):
                store.save_settings(settings)
            saved = (Path(folder) / "settings.json").read_text("utf-8")
            self.assertNotIn("test-secret", saved)
            self.assertNotIn('"api_key"', saved)
            with patch("studio.storage._unprotect_key", return_value=settings["api_key"]):
                self.assertEqual(store.load_settings()["api_key"], settings["api_key"])
            store.save_jobs([{"id": "1", "state": "review", "label": "棉"}])
            self.assertEqual(store.load_jobs()[0]["label"], "棉")

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI integration")
    def test_windows_dpapi_roundtrip_and_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            settings = store.load_settings()
            settings["api_key"] = "local-test-key-123"
            store.save_settings(settings)
            self.assertNotIn("local-test-key-123", (Path(folder) / "settings.json").read_text("utf-8"))
            self.assertEqual(Store(Path(folder)).load_settings()["api_key"], "local-test-key-123")
            settings["api_key"] = ""
            store.save_settings(settings)
            self.assertEqual(store.load_settings()["api_key"], "")
            self.assertNotIn("_protected_api_key", (Path(folder) / "settings.json").read_text("utf-8"))

    def test_encryption_failure_preserves_prior_file(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.save_settings({"api_key": "", "concurrency": 3})
            original = (Path(folder) / "settings.json").read_bytes()
            with patch("studio.storage._protect_key", side_effect=StorageError("Encryption unavailable")):
                with self.assertRaises(StorageError):
                    store.save_settings({"api_key": "secret"})
            self.assertEqual((Path(folder) / "settings.json").read_bytes(), original)

    def test_threaded_saves_are_valid_and_corruption_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda number: store.save_jobs([{"id": number}]), range(20)))
            self.assertEqual(len(store.load_jobs()), 1)
            (Path(folder) / "jobs.json").write_text("bad json", encoding="utf-8")
            with self.assertRaises(StorageError):
                store.load_jobs()
            (Path(folder) / "settings.json").write_text(json.dumps({"api_key": "plaintext"}), encoding="utf-8")
            with self.assertRaises(StorageError):
                store.load_settings()

    def test_custom_data_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"FABRIC_STUDIO_DATA": folder}):
            self.assertEqual(default_data_dir(), Path(folder).resolve())


if __name__ == "__main__":
    unittest.main()
