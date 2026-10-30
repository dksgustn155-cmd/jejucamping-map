"""
전국문화축제표준데이터 수집 (행안부 표준, 2026-07-06 승인)
- 엔드포인트: https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api (키: DATA_GO_KR_KEY)
- ⭐ 좌표·개최기간·장소·내용이 구조화되어 있어 GPT 추출 불필요 → category='festival' 메인 레이어
- 제주 소식 뉴스(collect_festival.py)는 category='festival_news'로 분리 (RAG 원문 + GPT 보완용, 이슈 #12)
- 추천 점수의 '혼잡 회피' 신호(개최기간)로도 사용 (docs/recommendation-pipeline.md)

실행: python data_pipeline/collect_festival_std.py
※ build_db.py 가 테이블을 재생성하므로 build_db → collect_* 순서로 실행 (refresh_all.py 참고)
"""
import os
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "festival_std.jsonl"
URL = "https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api"


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
    q = urllib.parse.urlencode({"serviceKey": KEY, "pageNo": page, "numOfRows": rows, "type": "json"})
    with urllib.request.urlopen(f"{URL}?{q}", timeout=60) as r:
        return json.load(r)


def main():
    first = fetch_page(1, 1)
    header = first.get("response", {}).get("header", {})
    if header.get("resultCode") not in ("00", "0"):
        print(f"⚠️ API 응답: {header.get('resultCode')} {header.get('resultMsg')}")
        return
    total = int(first["response"]["body"].get("totalCount", 0))
    pages = (total + 999) // 1000
    print(f"전국문화축제: 총 {total:,}건 ({pages}페이지)")

    rows = []
    for p in range(1, pages + 1):
        items = fetch_page(p).get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):
            items = [items]
        for it in items:
            name = (it.get("fstvlNm") or "").strip()
            start = (it.get("fstvlStartDate") or "").strip()
            rows.append({
                "id": f"festival:{name}|{start}",
                "name": name,
                "lat": to_float(it.get("latitude")),
                "lon": to_float(it.get("longitude")),
                "road_addr": (it.get("rdnmadr") or "").strip(),
                "lotno_addr": (it.get("lnmadr") or "").strip(),
                "tel": (it.get("phoneNumber") or "").strip(),
                "extra": {
                    "period": f"{start} ~ {(it.get('fstvlEndDate') or '').strip()}",
                    "start": start,
                    "end": (it.get("fstvlEndDate") or "").strip(),
                    "place": (it.get("opar") or "").strip(),
                    "summary": (it.get("fstvlCo") or "").strip()[:200],
                    "host": (it.get("mnnstNm") or "").strip(),
                    "url": (it.get("homepageUrl") or "").strip(),
                },
            })
        print(f"  p{p}/{pages} 누적 {len(rows):,}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='festival'")
    n = 0
    for r in rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "festival", r["name"], r["lat"], r["lon"], r["road_addr"],
             r["lotno_addr"], r["extra"]["period"], r["tel"],
             json.dumps(r["extra"], ensure_ascii=False)))
        n += 1
    con.commit()
    jeju = con.execute("SELECT COUNT(*) FROM facilities WHERE category='festival' "
                       "AND (road_addr LIKE '제주%' OR lotno_addr LIKE '제주%')").fetchone()[0]
    con.close()
    print(f"✅ DB 반영: festival {n:,}건 (좌표 있는 것) · 제주 {jeju}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
