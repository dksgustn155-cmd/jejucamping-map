"""
제주 심야약국 수집 (제주공공데이터 data.jeju.go.kr, XML)
- ⚠️ data.go.kr(apis.data.go.kr)와 다른 플랫폼: 파라미터가 `authApiKey`, 응답 XML, http
- 엔드포인트: http://data.jeju.go.kr/rest/nightpharmacy/getNightPharmacyList?authApiKey=KEY
- 좌표(la/lo, WGS84)·이름·주소·전화 제공. 야간 응급 편의 레이어
- 결과: data/raw/jeju_pharmacy.jsonl + facilities.db (category='pharmacy')

실행: python data_pipeline/collect_jeju_pharmacy.py
필요: .env 의 DATA_GO_KR_KEY (authApiKey로 사용)
"""
import os
import re
import json
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "jeju_pharmacy.jsonl"
URL = "http://data.jeju.go.kr/rest/nightpharmacy/getNightPharmacyList"


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


def main():
    with urllib.request.urlopen(f"{URL}?authApiKey={KEY}", timeout=30) as r:
        xml = r.read().decode("utf-8")

    items = re.findall(r"<list>(.*?)</list>", xml, re.S)
    print(f"심야약국: {len(items)}곳")

    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='pharmacy'")
    out, n = [], 0
    for block in items:
        d = {k: v for k, v in re.findall(r"<(\w+)>([^<]*)</\1>", block)}
        lat, lon = to_float(d.get("la")), to_float(d.get("lo"))
        row = {
            "id": f"pharmacy:{d.get('dataSid')}",
            "name": (d.get("dataTitle") or "심야약국").strip(),
            "lat": lat, "lon": lon,
            "addr": (d.get("adres") or "").strip(),
            "tel": (d.get("telNo") or "").strip(),
            "extra": {"area": d.get("area"), "content": d.get("dataContent")},
        }
        out.append(row)
        if lat is not None and lon is not None:
            con.execute(
                "INSERT OR REPLACE INTO facilities "
                "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row["id"], "pharmacy", row["name"], lat, lon, row["addr"], "", "", row["tel"],
                 json.dumps(row["extra"], ensure_ascii=False)))
            n += 1
    con.commit()
    con.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"DB 반영: pharmacy {n}곳 → {OUT_PATH}")


if __name__ == "__main__":
    main()
