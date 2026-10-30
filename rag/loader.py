import json
from pathlib import Path

from rag.config import DATA_RAW_DIR, SOURCE_FILES


def load_jsonl(file_path: Path):
    """JSONL 파일 하나를 읽어서 리스트로 반환"""
    records = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    return records


def load_all_data():
    """config.py에 정의된 모든 JSONL 파일을 읽는다."""
    all_records = []

    for filename in SOURCE_FILES:
        path = DATA_RAW_DIR / filename

        if not path.exists():
            print(f"[SKIP] {filename}")
            continue

        data = load_jsonl(path)

        print(f"[OK] {filename}: {len(data)}개")

        all_records.extend(data)

    print(f"\n총 {len(all_records)}개의 데이터를 불러왔습니다.")

    return all_records


if __name__ == "__main__":
    load_all_data()