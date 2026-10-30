"""
전국주차장정보표준데이터 수집 (행안부 표준데이터, 2026-07-06 활용승인)
- 엔드포인트: https://api.data.go.kr/openapi/tn_pubr_prkplce_info_api
- 키: .env 의 DATA_GO_KR_KEY (기존 키 그대로. 화장실 표준API와 동일 키)
- category='parking_public' 로 DB 반영 (둔치주차장 'parking' 과 별개 — 추천 후보군 핵심, docs/recommendation-pipeline.md)
- ⭐ 좌표(latitude/longitude) 포함이라 지오코딩 불필요

⚠️ 승인 직후엔 'SERVICE KEY IS NOT REGISTERED'(코드30)가 뜰 수 있음 = 포털 반영 지연.
   1시간~하루 뒤 재시도. 이 스크립트는 그 상태를 감지해 친절히 안내함.
※ build_db.py 가 테이블을 재생성하므로 build_db → collect_parking 순서로 실행.

실행: python data_pipeline/collect_parking.py
"""
import os
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "parking_public.jsonl"
URL = "https://api.data.go.kr/openapi/tn_pubr_prkplce_info_api"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
KEY = os.environ.get("DATA_GO_KR_KEY")
assert KEY and "키" not in KEY, ".env 에 DATA_GO_KR_KEY 를 설정하세요"


def to_float(v):
    try:
        f = float(v)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def fetch_page(page, rows=1000):
    q = urllib.parse.urlencode({
        "serviceKey": KEY, "pageNo": page, "numOfRows": rows, "type": "json",
    })
    with urllib.request.urlopen(f"{URL}?{q}", timeout=60) as r:
        return json.load(r)


def main():
    first = fetch_page(1, 1)
    header = first.get("response", {}).get("header", {})
    if header.get("resultCode") not in ("00", "0", None):
        print(f"⚠️ API 응답: {header.get('resultCode')} {header.get('resultMsg')}")
        if "NOT REGISTERED" in (header.get("resultMsg") or ""):
            print("→ 방금 승인받은 키라 아직 포털 반영 전입니다. 1시간~하루 뒤 다시 실행하세요.")
        return

    total = int(first["response"]["body"].get("totalCount", 0))
    pages = (total + 999) // 1000
    print(f"전국주차장표준데이터: 총 {total:,}건 ({pages}페이지)")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in range(1, pages + 1):
        items = fetch_page(p).get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):          # 단건일 때 dict로 오는 경우 방어
            items = [items]
        for it in items:
            rows.append({
                "id": f"parking_public:{it.get('prkplceNo') or it.get('prkplceNm')}",
                "name": (it.get("prkplceNm") or "").strip(),
                "lat": to_float(it.get("latitude")),
                "lon": to_float(it.get("longitude")),
                "road_addr": (it.get("rdnmadr") or "").strip(),
                "lotno_addr": (it.get("lnmadr") or "").strip(),
                "tel": (it.get("phoneNumber") or "").strip(),
                "extra": {
                    "gubun": it.get("prkplceSe"),           # 공영/민영
                    "type": it.get("prkplceType"),          # 노상/노외/부설
                    "capacity": it.get("prkcmprt"),         # 주차구획수
                    "oper_day": it.get("operDay"),          # 운영요일
                    "open": it.get("weekdayOperOpenHhmm"),
                    "close": it.get("weekdayOperColseHhmm"),
                    "charge_info": it.get("parkingchrgeInfo"),  # 유료/무료
                    "basic_time": it.get("basicTime"),
                    "basic_charge": it.get("basicCharge"),
                    "manager": it.get("institutionNm"),
                },
            })
        print(f"  p{p}/{pages} 누적 {len(rows):,}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='parking_public'")
    n = 0
    for r in rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "parking_public", r["name"], r["lat"], r["lon"], r["road_addr"],
             r["lotno_addr"], f"{r['extra'].get('open') or ''}~{r['extra'].get('close') or ''}",
             r["tel"], json.dumps(r["extra"], ensure_ascii=False)))
        n += 1
    con.commit()
    jeju = con.execute(
        "SELECT COUNT(*) FROM facilities WHERE category='parking_public' "
        "AND road_addr LIKE '제주%'").fetchone()[0]
    con.close()
    print(f"\n✅ DB 반영: parking_public {n:,}건 (좌표 있는 것) · 제주 {jeju}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
