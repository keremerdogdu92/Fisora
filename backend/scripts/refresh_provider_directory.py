from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


EPDK_GAS_URL = "https://apigateway.epdk.gov.tr/dogalgazDagitimLisansiSorgula/"
DIRECTORY_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "provider_directory.v1.json"


def build_epdk_gas_records(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    seen_tax_ids: set[str] = set()
    for row in rows:
        if row.get("lisansDurumu") != "ONAYLANDI":
            continue
        tax_id = re.sub(r"\D", "", str(row.get("vergiNo") or ""))
        title = str(row.get("lisansSahibiUnvani") or "").strip()
        if len(tax_id) != 10 or not title:
            continue
        if tax_id in seen_tax_ids:
            raise ValueError(f"epdk_gas_duplicate_tax_id:{tax_id}")
        seen_tax_ids.add(tax_id)
        records.append(
            {
                "provider_id": f"epdk_gas_{tax_id}",
                "service_profile": "natural_gas",
                "tax_ids": [tax_id],
                "titles": [title],
                "source": "epdk_active_distribution_license",
            }
        )
    return sorted(records, key=lambda record: str(record["tax_ids"][0]))


def fetch_epdk_gas_rows() -> list[dict[str, object]]:
    request = Request(
        EPDK_GAS_URL,
        data=b'{"lisansDurumu":["ONAYLANDI"]}',
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("epdk_gas_response_invalid")
    return [row for row in payload if isinstance(row, dict)]


def refresh_directory(*, directory_path: Path = DIRECTORY_PATH) -> int:
    payload = json.loads(directory_path.read_text(encoding="utf-8"))
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise ValueError("provider_directory_providers_missing")
    gas_records = build_epdk_gas_records(fetch_epdk_gas_rows())
    non_gas_records = [
        record
        for record in providers
        if isinstance(record, dict) and record.get("service_profile") != "natural_gas"
    ]
    payload["providers"] = [*non_gas_records, *gas_records]
    payload["version"] = int(payload.get("version") or 0) + 1
    directory_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(gas_records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh active Turkish natural-gas providers from EPDK.")
    parser.add_argument("--output", type=Path, default=DIRECTORY_PATH)
    args = parser.parse_args()
    print(f"refreshed_natural_gas_providers={refresh_directory(directory_path=args.output)}")


if __name__ == "__main__":
    main()
