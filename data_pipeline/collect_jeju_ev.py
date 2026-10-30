"""
제주 전기차 충전소 수집 (제주 ITS센터 OPEN API, 2026-07-06 승인)
- infoEvInfoList: 충전소 기본정보 8,664개 (WGS84 좌표·24시간·무료 여부)
- category='ev_charger' 로 DB 반영
- ⚠️ 실시간 급속/완속 가용(infoEvList)은 값이 계속 바뀌므로 여기 저장 안 함 →
  서빙 시(백엔드)에서 /api/infoEvList 호출해 id로 조인 (팀원 A/C)

실행: python data_pipeline/collect_jeju_ev.py
필요: .env 의 JEJU_ITS_CODE
※ build_db.py 로 테이블을 다시 만들면 ev_charger가 지워지므로, build_db → collect_* 순서로 실행
"""
import os
import json
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "jeju_ev.jsonl"


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
CODE = os.environ.get("JEJU_ITS_CODE")
assert CODE and "코드" not in CODE, ".env 에 JEJU_ITS_CODE 를 설정하세요"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    url = f"http://api.jejuits.go.kr/api/infoEvInfoList?code={CODE}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    items = data.get("info", [])
    print(f"제주 전기차 충전소: {len(items):,}개")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for it in items:
        lat, lon = to_float(it.get("x_crdn")), to_float(it.get("y_crdn"))
        rows.append({
            "id": f"ev:{it.get('id')}",
            "name": (it.get("name") or "").strip(),
            "lat": lat, "lon": lon,
            "addr": (it.get("addr") or "").strip(),
            "use_time": (it.get("use_time") or "").strip(),   # "24시간 이용가능" 등
            "free": (it.get("free") or "").strip(),            # 무료 Y/N
            "operator": (it.get("b_name") or "").strip(),      # 사업자
            "tel": (it.get("b_call") or "").strip(),
        })
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # DB 반영
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='ev_charger'")
    n = 0
    for r in rows:
        if r["lat"] is None:
            continue
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "ev_charger", r["name"], r["lat"], r["lon"], r["addr"], "",
             r["use_time"], r["tel"],
             json.dumps({"free": r["free"], "operator": r["operator"], "use_time": r["use_time"]},
                        ensure_ascii=False)))
        n += 1
    con.commit()
    con.close()
    print(f"DB 반영: ev_charger {n:,}개 (좌표 있는 것만) → {OUT_PATH}")


if __name__ == "__main__":
    main()
