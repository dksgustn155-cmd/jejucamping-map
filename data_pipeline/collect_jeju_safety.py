"""
제주 특화 안전/편의 데이터 수집 (data.go.kr 제주시 6510000, 2026-07-06 승인)
- 월파 감시 CCTV   waveoverCctvInfoService/getWaveoverCctvList  (해변 파도 위험 실시간 영상)
- 하천 감시 CCTV   riverCctvService/getRiverCctvList            (하천 범람 실시간 영상)
- 클린하우스       cleanHouseService/getCleanHouseList          (캠퍼 쓰레기 배출)
- 전부 WGS84 좌표(laCrdnt/loCrdnt) + CCTV는 실시간 스트림 URL(cctvUrl) 포함
- 한글 파라미터 없어 어디서나 수집 가능

결과: data/raw/jeju_safety.jsonl + facilities.db (category: 'cctv' / 'cleanhouse')
실행: python data_pipeline/collect_jeju_safety.py
필요: .env 의 DATA_GO_KR_KEY
※ build_db → collect_* 순서
"""
import os
import json
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "jeju_safety.jsonl"
BASE = "https://apis.data.go.kr/6510000"


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
KEY = os.environ.get("DATA_GO_KR_KEY")
assert KEY and "키" not in KEY, ".env 에 DATA_GO_KR_KEY 를 설정하세요"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_all(service: str, op: str) -> list:
    """6510000 플랫폼 전체 수집 (response.body.items.item)"""
    rows, page = [], 1
    while True:
        url = f"{BASE}/{service}/{op}?serviceKey={KEY}&pageNo={page}&numOfRows=1000&returnType=json"
        with urllib.request.urlopen(url, timeout=40) as r:
            data = json.load(r)
        body = data.get("response", {}).get("body", {})
        items = (body.get("items") or {}).get("item") or []
        if isinstance(items, dict):
            items = [items]
        rows += items
        total = int(body.get("totalCount", 0))
        if len(rows) >= total or not items:
            return rows
        page += 1


def main():
    sources = [
        ("cctv", "wave", "waveoverCctvInfoService", "getWaveoverCctvList"),
        ("cctv", "river", "riverCctvService", "getRiverCctvList"),
        ("cleanhouse", None, "cleanHouseService", "getCleanHouseList"),
    ]
    all_out = []
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category IN ('cctv','cleanhouse')")

    for category, subtype, service, op in sources:
        items = fetch_all(service, op)
        print(f"  {service}: {len(items)}개")
        for d in items:
            lat, lon = to_float(d.get("laCrdnt")), to_float(d.get("loCrdnt"))
            # 원본 오류 방어: 소수점 누락 등으로 제주 범위 밖이면 버림 (예: 경도 12646377258)
            if lat is not None and lon is not None and not (33.0 <= lat <= 34.0 and 126.0 <= lon <= 127.1):
                lat = lon = None
            if lat is None or lon is None:
                continue
            if category == "cctv":
                name = (d.get("spotNm") or "CCTV").strip()
                extra = {"cctv_type": subtype, "cctv_url": d.get("cctvUrl"), "use_yn": d.get("useYn")}
                addr = ""
            else:  # cleanhouse
                name = (d.get("hsmpNm") or d.get("seNm") or "클린하우스").strip()
                extra = {"emd": d.get("emdNm"), "pattern": d.get("pttnNm")}
                addr = (d.get("rnAdres") or d.get("lnmAdres") or "").strip()
            row = {"id": f"{category}:{d.get('dataCd')}", "category": category,
                   "name": name, "lat": lat, "lon": lon, "addr": addr, "extra": extra}
            all_out.append(row)
            con.execute(
                "INSERT OR REPLACE INTO facilities "
                "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row["id"], category, name, lat, lon, addr, "", "", "",
                 json.dumps(extra, ensure_ascii=False)))
    con.commit()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in all_out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    cctv = con.execute("SELECT COUNT(*) FROM facilities WHERE category='cctv'").fetchone()[0]
    ch = con.execute("SELECT COUNT(*) FROM facilities WHERE category='cleanhouse'").fetchone()[0]
    con.close()
    print(f"DB 반영: cctv {cctv} / cleanhouse {ch} → {OUT_PATH}")


if __name__ == "__main__":
    main()
