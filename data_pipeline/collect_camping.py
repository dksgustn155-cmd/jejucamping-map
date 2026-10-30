"""
야영장(캠핑장) 수집 스크립트
- API: 한국관광공사_고캠핑 정보 조회서비스 (basedList)
- 전국 등록 야영장. ✅ 좌표(mapX=경도, mapY=위도) 포함 → 지오코딩 불필요
- 결과: data/raw/camping.jsonl

실행: python data_pipeline/collect_camping.py
필요: .env 의 DATA_GO_KR_KEY
"""
import os
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path


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

ENDPOINT = "https://apis.data.go.kr/B551011/GoCamping/basedList"
NUM_ROWS = 1000

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "camping.jsonl"

# 서빙에 쓸 핵심 필드만 추림
KEEP = [
    "contentId", "facltNm", "induty", "lctCl", "doNm", "sigunguNm",
    "addr1", "addr2", "mapX", "mapY", "tel", "homepage", "resveUrl", "resveCl",
    "gnrlSiteCo", "autoSiteCo", "glampSiteCo", "caravSiteCo", "sbrsCl", "posblFcltyCl",
    "toiletCo", "swrmCt", "operPdCl", "operDeCl",
]


def fetch_page(page_no: int, retries: int = 3) -> dict:
    qs = urllib.parse.urlencode({
        "serviceKey": KEY,
        "numOfRows": NUM_ROWS,
        "pageNo": page_no,
        "MobileOS": "ETC",
        "MobileApp": "campingmap",
        "_type": "json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{ENDPOINT}?{qs}", timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  ! page {page_no} 재시도 {attempt+1}/{retries}: {e}")
            time.sleep(3)


def main():
    first = fetch_page(1)
    body = first["response"]["body"]
    total = int(body["totalCount"])
    total_pages = (total + NUM_ROWS - 1) // NUM_ROWS
    print(f"총 {total:,}개 야영장 / {total_pages} 페이지")

    written = 0
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for page in range(1, total_pages + 1):
            data = first if page == 1 else fetch_page(page)
            items = data["response"]["body"]["items"]["item"]
            if isinstance(items, dict):
                items = [items]
            for it in items:
                row = {k: it.get(k, "") for k in KEEP}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            print(f"  page {page}/{total_pages} → 누적 {written:,}")
            time.sleep(0.2)
    print(f"완료: {written:,}개 → {OUT_PATH}")


if __name__ == "__main__":
    main()
