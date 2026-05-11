import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from career_bot import master_data


def main():
    parser = argparse.ArgumentParser(description="Generate Sweepy data JSONs from master.mdb.")
    parser.add_argument("--db-path", default=None, help="Path to Umamusume master.mdb.")
    args = parser.parse_args()

    result = master_data.generate(ROOT, args.db_path)
    if not result.get("success"):
        print(result.get("detail") or "master_data generation failed")
        return 1

    for item in result.get("extracted") or []:
        print(f"extracted {item['table']} ({item['rows']} rows)")
    for table_name in result.get("skipped") or []:
        print(f"skipped {table_name}")
    legacy = result.get("legacy") or {}
    for item in legacy.get("generated") or []:
        detail = ", ".join(f"{key}={value}" for key, value in item.items() if key != "file")
        print(f"synthesized {item['file']}" + (f" ({detail})" if detail else ""))
    for file_name in legacy.get("preserved") or []:
        print(f"preserved {file_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
