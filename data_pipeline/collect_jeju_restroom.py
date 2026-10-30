"""
제주 화장실 (제주시 CSV, 좌표 정밀 제공판) 수집
- 전국 화장실 API는 좌표가 없어 지오코딩했지만, 제주시 CSV는 위/경도를 직접 제공 → "제주는 더 정밀"
- 원본 CSV: 프로젝트 루트 `제주특별자치도 제주시_공중화장실_*.csv` (cp949 인코딩, git 제외)
- 결과: data/raw/jeju_restroom.jsonl
- ⚠️ DB 반영은 기본 OFF (전국 restroom과 제주시 화장실이 중복될 수 있어 표시 정책 팀 결정 필요, 이슈 #1)
    반영하려면:  python data_pipeline/collect_jeju_restroom.py --to-db

실행: python data_pipeline/collect_jeju_restroom.py [--to-db]
"""
import sys
import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "jeju_restroom.jsonl"


def find_csv():
    for p in ROOT.glob("*공중화장실*.csv"):
        return p
    return None


def read_rows():
    csv_path = find_csv()
    assert csv_path, "제주 화장실 CSV를 프로젝트 루트에 두세요 (제주*공중화장실*.csv)"
    # 인코딩 자동 시도
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(csv_path, encoding=enc) as f:
                rows = list(csv.DictReader(f))
            return rows
        except UnicodeDecodeError:
            continue
    raise RuntimeError("CSV 인코딩 판별 실패")


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(to_db: bool):
    rows = read_rows()
    print(f"제주 화장실 CSV: {len(rows):,}건")

    out = []
    for d in rows:
        lat = to_float(d.get("위도 좌표"))
        lon = to_float(d.get("경도 좌표"))
        out.append({
            "id": f"restroom_jeju:{d.get('데이터 코드')}",
            "name": (d.get("화장실 명") or "").strip(),
            "lat": lat, "lon": lon,
            "road_addr": (d.get("도로명 주소") or "").strip(),
            "lotno_addr": (d.get("지번 주소") or "").strip(),
            "open_hours": (d.get("개방 시간 정보") or "").strip(),
            "tel": (d.get("전화번호") or "").strip(),
            "extra": {
                "male_toilet": d.get("남성 대변기 수"),
                "female_toilet": d.get("여성 대변기 수"),
                "disabled": d.get("남성 장애인 대변기 수"),
                "diaper": d.get("기저귀 교환대 설치 여부"),
                "emerg_bell": d.get("비상 벨 설치 여부"),
                "cctv": d.get("화장실 입구 CCTV 설치 여부"),
                "mng": d.get("관리 기관 명"),
                "source": "제주시_정밀좌표",
            },
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with_coord = sum(1 for r in out if r["lat"] is not None)
    print(f"저장: {len(out):,}건 (좌표 {with_coord:,}) → {OUT_PATH}")

    if to_db:
        con = sqlite3.connect(DB_PATH, timeout=30)
        con.execute("DELETE FROM facilities WHERE category='restroom_jeju'")
        for r in out:
            if r["lat"] is None:
                continue
            con.execute(
                "INSERT OR REPLACE INTO facilities "
                "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (r["id"], "restroom_jeju", r["name"], r["lat"], r["lon"],
                 r["road_addr"], r["lotno_addr"], r["open_hours"], r["tel"],
                 json.dumps(r["extra"], ensure_ascii=False)))
        con.commit()
        con.close()
        print(f"DB 반영 완료: category='restroom_jeju' (⚠️ 전국 restroom과 중복 표시 주의)")


if __name__ == "__main__":
    main(to_db="--to-db" in sys.argv)
