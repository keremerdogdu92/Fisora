from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.refresh_provider_directory import build_epdk_gas_records


class ProviderDirectoryRefreshTests(unittest.TestCase):
    def test_epdk_active_gas_license_rows_become_direct_match_records(self) -> None:
        records = build_epdk_gas_records(
            [
                {
                    "lisansDurumu": "ONAYLANDI",
                    "lisansSahibiUnvani": "ARH BİNGÖL DOĞAL GAZ DAĞITIM ANONİM ŞİRKETİ",
                    "vergiNo": "0741215923",
                },
                {
                    "lisansDurumu": "SONLANDIRILDI",
                    "lisansSahibiUnvani": "Eski Gaz A.Ş.",
                    "vergiNo": "1234567890",
                },
            ]
        )

        self.assertEqual(
            records,
            [
                {
                    "provider_id": "epdk_gas_0741215923",
                    "service_profile": "natural_gas",
                    "tax_ids": ["0741215923"],
                    "titles": ["ARH BİNGÖL DOĞAL GAZ DAĞITIM ANONİM ŞİRKETİ"],
                    "source": "epdk_active_distribution_license",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
