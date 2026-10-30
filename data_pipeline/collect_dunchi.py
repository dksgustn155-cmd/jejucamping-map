"""
둔치주차장 수집·통합 스크립트 (재난안전데이터 공유플랫폼, 2026-07-06 승인)
= 이 서비스의 핵심 데이터: "차박 후보지 + 정부 침수위험등급"

4개 API를 THINGS_MNG_NO 로 조인:
  본체(DSSP-IF-10830, 563 주소점)  좌표 EPSG:5179 → WGS84 변환
  속성(DSSP-IF-00162, 322 주차장)  이름·위험등급(RSK_GRD)·주차면수·하천명 ⭐
  영역(DSSP-IF-00160, 322 폴리곤)  부지 POLYGON, EPSG:3857 → WGS84
  진입로(DSSP-IF-00161, 278 라인)  LINESTRING, EPSG:3857 → WGS84

결과:
  data/raw/dunchi.jsonl (주차장 1곳 = 1줄, 폴리곤·진입로 포함)
  facilities.db 에 category='parking' 으로 반영

실행: python data_pipeline/collect_dunchi.py
필요: .env 의 SAFETY_DUNCHI_*_KEY 4개, pyproj
주의: 키당 일일 1,000건 호출 제한 — 이 스크립트는 API당 1~2회만 호출
"""
import os
import json
import math
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "dunchi.jsonl"
BASE = "https://www.safetydata.go.kr/V2/api"


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
KEYS = {
    "main": os.environ.get("SAFETY_DUNCHI_MAIN_KEY"),
    "attr": os.environ.get("SAFETY_DUNCHI_ATTR_KEY"),
    "zone": os.environ.get("SAFETY_DUNCHI_ZONE_KEY"),
    "road": os.environ.get("SAFETY_DUNCHI_ROAD_KEY"),
}
ENDPOINTS = {
    "main": "DSSP-IF-10830",
    "attr": "DSSP-IF-00162",
    "zone": "DSSP-IF-00160",
    "road": "DSSP-IF-00161",
}
assert all(KEYS.values()), ".env 에 SAFETY_DUNCHI_*_KEY 4개를 설정하세요"


def fetch_all(kind: str) -> list:
    """한 API의 전체 행 수집 (건수가 적어 1~2회 호출로 끝)"""
    rows, page = [], 1
    while True:
        qs = urllib.parse.urlencode({
            "serviceKey": KEYS[kind], "pageNo": page,
            "numOfRows": 1000, "returnType": "json",
        })
        with urllib.request.urlopen(f"{BASE}/{ENDPOINTS[kind]}?{qs}", timeout=60) as r:
            data = json.load(r)
        body = data.get("body") or []
        rows += body
        total = int(data.get("totalCount", 0))
        if len(rows) >= total or not body:
            return rows
        page += 1


# ── 좌표 변환 ──────────────────────────────────────────────────────────
def merc_to_wgs84(x: float, y: float):
    """EPSG:3857(Web Mercator) → (lat, lon)"""
    lon = x / 20037508.34 * 180.0
    lat = y / 20037508.34 * 180.0
    lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lat, lon


def parse_geom(geom: str):
    """'POLYGON((x y,...))' / 'LINESTRING(x y,...)' → [[lat,lon], ...] (WGS84)"""
    if not geom:
        return None
    inner = geom[geom.rfind("((") + 2: geom.find("))")] if "((" in geom \
        else geom[geom.find("(") + 1: geom.rfind(")")]
    pts = []
    for pair in inner.split(","):
        xy = pair.split()
        if len(xy) >= 2:
            lat, lon = merc_to_wgs84(float(xy[0]), float(xy[1]))
            pts.append([round(lat, 6), round(lon, 6)])
    return pts or None


def main():
    from pyproj import Transformer
    tf5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    print("수집 중 (API당 1회 호출, 일일한도 1,000 안에서 여유)...")
    main_rows = fetch_all("main")
    attr_rows = fetch_all("attr")
    zone_rows = fetch_all("zone")
    road_rows = fetch_all("road")
    print(f"  본체 {len(main_rows)} / 속성 {len(attr_rows)} / 영역 {len(zone_rows)} / 진입로 {len(road_rows)}")

    # 조인 준비: THINGS_MNG_NO 기준
    # 본체(주소점 여러 개) → 대표 좌표 1개 (첫 주소점, EPSG:5179→WGS84)
    coord_by_id: dict = {}
    addr_by_id: dict = {}
    for m in main_rows:
        mid = m["OBJT_MNG_NO"]
        if mid not in coord_by_id and m.get("XCRD") and m.get("YCRD"):
            lon, lat = tf5179.transform(float(m["XCRD"]), float(m["YCRD"]))
            coord_by_id[mid] = (round(lat, 6), round(lon, 6))
            addr_by_id[mid] = (m.get("ADDR") or "").strip()

    zone_by_id = {}
    for z in zone_rows:
        zone_by_id.setdefault(z["THINGS_MNG_NO"], parse_geom(z.get("GEOM")))
    road_by_id: dict = {}
    for r in road_rows:
        road_by_id.setdefault(r["THINGS_MNG_NO"], []).append(parse_geom(r.get("GEOM")))

    # 속성(322) 을 마스터로 통합
    out = []
    no_coord = 0
    for a in attr_rows:
        aid = a["THINGS_MNG_NO"]
        poly = zone_by_id.get(aid)
        # 대표 좌표: 본체 주소점 → 없으면 폴리곤 중심
        if aid in coord_by_id:
            lat, lon = coord_by_id[aid]
        elif poly:
            lat = sum(p[0] for p in poly) / len(poly)
            lon = sum(p[1] for p in poly) / len(poly)
            lat, lon = round(lat, 6), round(lon, 6)
        else:
            lat = lon = None
            no_coord += 1
        out.append({
            "id": aid,
            "name": (a.get("THINGS_NM") or "둔치주차장").strip(),
            "lat": lat, "lon": lon,
            "addr": addr_by_id.get(aid, f"{a.get('CTPV_NM','')} {a.get('SGG_NM','')}".strip()),
            "risk_grade": (a.get("RSK_GRD") or "").strip(),        # 침수위험등급 (1~3)
            "risk_grade_nm": (a.get("RSK_GRD_NM") or "").strip(),
            "capacity": a.get("PRK_PSBLTY_CNT"),                   # 주차 가능 대수
            "river": (a.get("RVR_NM") or "").strip(),              # 하천명
            "shape": (a.get("FCLT_SHP_NM") or "").strip(),         # 시설 형태
            "polygon": poly,                                        # 부지 [[lat,lon],...]
            "access_roads": road_by_id.get(aid),                    # 진입로 선들
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"저장: {len(out)}곳 → {OUT_PATH} (좌표없음 {no_coord})")

    # DB 반영 (category='parking')
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='parking'")
    for r in out:
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"parking:{r['id']}", "parking", r["name"], r["lat"], r["lon"],
             r["addr"], "", "", "",
             json.dumps({
                 "risk_grade": r["risk_grade"], "risk_grade_nm": r["risk_grade_nm"],
                 "capacity": r["capacity"], "river": r["river"], "shape": r["shape"],
                 "polygon": r["polygon"], "access_roads": r["access_roads"],
             }, ensure_ascii=False)))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM facilities WHERE category='parking'").fetchone()[0]
    jeju = con.execute(
        "SELECT COUNT(*) FROM facilities WHERE category='parking' AND road_addr LIKE '%제주%'"
    ).fetchone()[0]
    con.close()
    print(f"DB 반영: parking {n}곳 (제주 {jeju}곳)")

    # 위험등급 분포 출력 (활용 설계 참고용)
    from collections import Counter
    grades = Counter((r["risk_grade_nm"] or "미상") for r in out)
    print("위험등급 분포:", dict(grades))


if __name__ == "__main__":
    main()
