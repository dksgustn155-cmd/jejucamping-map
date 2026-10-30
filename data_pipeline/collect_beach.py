"""
해수욕장 수집 스크립트 (해양수산부_해수욕장정보 서비스)
- API: 1192000/service/OceansBeachInfoService1/getOceansBeachInfo1
- ⚠️ SIDO_NM 이 **짧은 시도명**(부산/제주…)이어야 함. 긴 이름(부산광역시)은 안 됨 — Phase 1 검증
- ⚠️ **한국 IP(본인 PC)에서 실행** 필요. 해외/클라우드 IP는 에러가 아니라 code 00에 결과가 빈다(0건) — 검증됨(2026-07-06)
- 결과: data/raw/beach.jsonl + facilities.db (category='beach')

실행: python data_pipeline/collect_beach.py
필요: .env 의 DATA_GO_KR_KEY
※ build_db.py 로 테이블 재생성 시 지워지므로, build_db → collect_* 순서로 실행
"""
import os
import json
import time
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "beach.jsonl"
ENDPOINT = "https://apis.data.go.kr/1192000/service/OceansBeachInfoService1/getOceansBeachInfo1"

# 해수욕장이 있는 연안 시도 (짧은 이름). 내륙(서울/대구/대전/광주/세종/충북)은 제외
SIDO_LIST = ["부산", "인천", "울산", "경기", "강원", "충남", "전북", "전남", "경북", "경남", "제주"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


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
        f = float(v)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def fetch_sido(sido: str) -> list:
    qs = urllib.parse.urlencode({
        "serviceKey": KEY, "SIDO_NM": sido,
        "numOfRows": 1000, "pageNo": 1, "resultType": "json",
    })
    req = urllib.request.Request(f"{ENDPOINT}?{qs}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    root = data.get("getOceansBeachInfo", {})
    items = root.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def main():
    all_items = []
    for sido in SIDO_LIST:
        try:
            items = fetch_sido(sido)
            print(f"  {sido}: {len(items)}개")
            all_items += items
        except Exception as e:
            print(f"  {sido}: 실패 - {e} (한국 IP에서 재시도하세요)")
        time.sleep(0.3)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for it in all_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"저장: {len(all_items)}개 → {OUT_PATH}")

    # DB 반영 (build_db.rows_beach 와 동일한 매핑, id = beach:시도:이름)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='beach'")
    n = 0
    for d in all_items:
        lat, lon = to_float(d.get("lat")), to_float(d.get("lon"))
        if lat is None or lon is None:
            continue  # 좌표 없는 해수욕장(일부 null)은 지도에 못 찍으므로 스킵
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"beach:{d.get('sido_nm','')}:{d.get('sta_nm','')}", "beach",
             (d.get("sta_nm") or "").strip(), lat, lon,
             f"{d.get('sido_nm','')} {d.get('gugun_nm','')}".strip(), "", "",
             (d.get("link_tel") or "").strip(),
             json.dumps({
                 "beach_wid": d.get("beach_wid"), "beach_len": d.get("beach_len"),
                 "beach_knd": d.get("beach_knd"), "link": d.get("link_addr"),
             }, ensure_ascii=False)))
        n += 1
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM facilities WHERE category='beach'").fetchone()[0]
    con.close()
    print(f"DB 반영: beach {n}개 (좌표 있는 것) / 전체 수집 {len(all_items)}")


if __name__ == "__main__":
    main()
