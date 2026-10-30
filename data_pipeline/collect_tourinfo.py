"""
전국관광안내소표준데이터 수집 (행안부 표준, 2026-07-06 승인)
- 엔드포인트: https://api.data.go.kr/openapi/tn_pubr_public_trsmic_api (키: DATA_GO_KR_KEY)
- category='tourinfo' 지도 레이어 (여행자 편의)

실행: python data_pipeline/collect_tourinfo.py
"""
import os
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "tourinfo.jsonl"
URL = "https://api.data.go.kr/openapi/tn_pubr_public_trsmic_api"


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


def main():
    q = urllib.parse.urlencode({"serviceKey": KEY, "pageNo": 1, "numOfRows": 1000, "type": "json"})
    with urllib.request.urlopen(f"{URL}?{q}", timeout=60) as r:
        data = json.load(r)
    header = data.get("response", {}).get("header", {})
    if header.get("resultCode") not in ("00", "0"):
        print(f"⚠️ API 응답: {header.get('resultCode')} {header.get('resultMsg')}")
        return
    items = data["response"]["body"].get("items", [])
    if isinstance(items, dict):
        items = [items]
    print(f"전국관광안내소: {len(items)}건")

    rows = []
    for it in items:
        langs = [n for n, y in [("영어", "engGuidanceYn"), ("일어", "jpGuidanceYn"), ("중국어", "chGuidanceYn")]
                 if (it.get(y) or "").upper() == "Y"]
        rows.append({
            "id": f"tourinfo:{(it.get('trsmicNm') or '').strip()}|{(it.get('signguNm') or '').strip()}",
            "name": (it.get("trsmicNm") or "").strip(),
            "lat": to_float(it.get("latitude")),
            "lon": to_float(it.get("longitude")),
            "road_addr": (it.get("rdnmadr") or it.get("trsmicLc") or "").strip(),
            "lotno_addr": (it.get("lnmadr") or "").strip(),
            "open_hours": f"{(it.get('summerOperOpenHhmm') or '').strip()}~{(it.get('summerOperCloseHhmm') or '').strip()}",
            "tel": (it.get("phoneNumber") or "").strip(),
            "extra": {
                "intro": (it.get("trsmicIntrcn") or "").strip()[:150],
                "lang": " · ".join(langs),
                "rest": (it.get("rstde") or "").strip(),
            },
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='tourinfo'")
    n = 0
    for r in rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "tourinfo", r["name"], r["lat"], r["lon"], r["road_addr"],
             r["lotno_addr"], r["open_hours"], r["tel"],
             json.dumps(r["extra"], ensure_ascii=False)))
        n += 1
    con.commit()
    jeju = con.execute("SELECT COUNT(*) FROM facilities WHERE category='tourinfo' "
                       "AND (road_addr LIKE '제주%' OR lotno_addr LIKE '제주%')").fetchone()[0]
    con.close()
    print(f"✅ DB 반영: tourinfo {n}건 (좌표 있는 것) · 제주 {jeju}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
