"""
공중화장실 수집 스크립트
- API: 행정안전부_공중화장실정보 조회서비스 (info_v2)
- 전국 약 59,768건 (2026-07 기준)
- ⚠️ 이 API는 좌표(위경도)를 제공하지 않음 → 이후 geocode_restroom.py에서 주소→좌표 변환 필요
- 결과: data/raw/restroom.jsonl (한 줄에 화장실 1개, JSON)

실행: python data_pipeline/collect_restroom.py
필요: .env 의 DATA_GO_KR_KEY
"""
import os
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

# ── .env 로드 (python-dotenv 없이 간단 파싱) ──────────────────────────
def load_env():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())

load_env()
KEY = os.environ.get("DATA_GO_KR_KEY")
assert KEY and KEY != "여기에_키_입력", ".env 에 DATA_GO_KR_KEY 를 설정하세요"

ENDPOINT = "https://apis.data.go.kr/1741000/public_restroom_info_v2/info_v2"
NUM_ROWS = 1000  # 페이지당 건수

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "restroom.jsonl"


def fetch_page(page_no: int, retries: int = 3) -> dict:
    qs = urllib.parse.urlencode({
        "serviceKey": KEY,
        "pageNo": page_no,
        "numOfRows": NUM_ROWS,
        "type": "json",
    })
    url = f"{ENDPOINT}?{qs}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  ! page {page_no} 재시도 {attempt+1}/{retries}: {e}")
            time.sleep(3)


def main(limit_pages: int | None = None):
    # 첫 페이지로 총 건수 파악
    first = fetch_page(1)
    body = first["response"]["body"]
    total = int(body["totalCount"])
    total_pages = (total + NUM_ROWS - 1) // NUM_ROWS
    if limit_pages:
        total_pages = min(total_pages, limit_pages)
    print(f"총 {total:,}건 / {total_pages} 페이지 수집 시작")

    written = 0
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for page in range(1, total_pages + 1):
            data = first if page == 1 else fetch_page(page)
            items = data["response"]["body"]["items"]["item"]
            if isinstance(items, dict):  # 1건일 때 dict로 오는 경우 방어
                items = [items]
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
                written += 1
            print(f"  page {page}/{total_pages} → 누적 {written:,}건")
            time.sleep(0.2)  # 서버 예의상 약간의 간격

    print(f"완료: {written:,}건 → {OUT_PATH}")


if __name__ == "__main__":
    import sys
    # 인자로 페이지 제한 (테스트용). 예: python collect_restroom.py 1
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit_pages=limit)
