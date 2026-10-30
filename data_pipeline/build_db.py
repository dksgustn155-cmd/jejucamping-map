"""
SQLite 빌드 스크립트
- data/raw/*.jsonl 을 읽어 하나의 facilities 테이블로 통합
- 카테고리: restroom(화장실) / camping(야영장) / beach(해수욕장) / parking(주차장)
- 좌표(lat/lon)로 bounding-box 검색이 빠르도록 인덱스 생성
- ⚠️ 화장실은 원본에 좌표가 없음 → lat/lon NULL 로 넣고, geocode_restroom.py(Day 2)에서 채움

결과: data/facilities.db
실행: python data_pipeline/build_db.py
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "facilities.db"


def to_float(v):
    try:
        f = float(v)
        return f if f != 0 else None  # 0,0 좌표는 결측 취급
    except (TypeError, ValueError):
        return None


def rows_restroom():
    """화장실: 좌표 없음(NULL) → Day2 지오코딩에서 채움"""
    path = RAW / "restroom.jsonl"
    if not path.exists():
        return
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        yield {
            "id": f"restroom:{d.get('MNG_NO','')}",
            "category": "restroom",
            "name": d.get("RSTRM_NM", ""),
            "lat": None,
            "lon": None,
            "road_addr": d.get("LCTN_ROAD_NM_ADDR", ""),
            "lotno_addr": d.get("LCTN_LOTNO_ADDR", ""),
            "open_hours": d.get("OPN_HR", ""),
            "tel": d.get("TELNO", ""),
            "extra": json.dumps({
                "male_toilet": d.get("MALE_TOILT_CNT"),
                "female_toilet": d.get("FEMALE_TOILT_CNT"),
                "disabled": d.get("MALE_FRDBL_TOILT_CNT"),
                "diaper": d.get("DIAP_EXCHCON_EN"),
                "emerg_bell": d.get("EMRGNCBLL_INSTL_YN"),
                "cctv": d.get("RSTRM_ENTRAN_CCTV_INSTL_EN"),
                "mng": d.get("MNG_INST_NM"),
            }, ensure_ascii=False),
        }


def rows_camping():
    """야영장: mapX=경도(lon), mapY=위도(lat)"""
    path = RAW / "camping.jsonl"
    if not path.exists():
        return
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        addr = " ".join(x for x in [d.get("addr1", ""), d.get("addr2", "")] if x).strip()
        yield {
            "id": f"camping:{d.get('contentId','')}",
            "category": "camping",
            "name": d.get("facltNm", ""),
            "lat": to_float(d.get("mapY")),
            "lon": to_float(d.get("mapX")),
            "road_addr": addr,
            "lotno_addr": "",
            "open_hours": d.get("operPdCl", ""),
            "tel": d.get("tel", ""),
            "extra": json.dumps({
                "induty": d.get("induty"),
                "gnrl_site": d.get("gnrlSiteCo"),
                "auto_site": d.get("autoSiteCo"),
                "glamp_site": d.get("glampSiteCo"),
                "carav_site": d.get("caravSiteCo"),
                "homepage": d.get("homepage"),
                "resve_url": d.get("resveUrl"),
                "facility": d.get("sbrsCl"),
                # 추천 점수화용 (docs/recommendation-pipeline.md): 입지(산/숲/계곡/해변/강/호수/섬/도심)·주변시설
                "loc_type": d.get("lctCl"),
                "nearby": d.get("posblFcltyCl"),
            }, ensure_ascii=False),
        }


def rows_beach():
    """해수욕장: (샌드박스에선 한글 파라미터 Forbidden이라 미수집 가능) 있으면 로드"""
    path = RAW / "beach.jsonl"
    if not path.exists():
        return
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        # ⚠️ num은 시도별 조회 순번이라 전국에서 중복됨 → 시도+이름 조합으로 고유 ID 생성
        yield {
            "id": f"beach:{d.get('sido_nm','')}:{d.get('sta_nm','')}",
            "category": "beach",
            "name": d.get("sta_nm", ""),
            "lat": to_float(d.get("lat")),
            "lon": to_float(d.get("lon")),
            "road_addr": f"{d.get('sido_nm','')} {d.get('gugun_nm','')}".strip(),
            "lotno_addr": "",
            "open_hours": "",
            "tel": d.get("link_tel", ""),
            "extra": json.dumps({
                "beach_wid": d.get("beach_wid"),
                "beach_len": d.get("beach_len"),
                "beach_knd": d.get("beach_knd"),
                "link": d.get("link_addr"),
            }, ensure_ascii=False),
        }


def apply_geocode_cache(cur):
    """재빌드 시 지오코딩 결과 보존: geocode_cache.json의 주소→좌표를 화장실에 재적용.
    (이게 없으면 build_db 재실행 때 지오코딩한 좌표가 전부 NULL로 초기화됨!)"""
    cache_path = RAW / "geocode_cache.json"
    if not cache_path.exists():
        return 0
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    n = 0
    for row in cur.execute(
        "SELECT id, road_addr, lotno_addr FROM facilities "
        "WHERE category='restroom' AND lat IS NULL"
    ).fetchall():
        addr = row[1] or row[2]
        coord = cache.get(addr)
        if coord:
            cur.execute("UPDATE facilities SET lat=?, lon=? WHERE id=?", (coord[0], coord[1], row[0]))
            n += 1
    return n


def main():
    con = sqlite3.connect(DB_PATH, timeout=30)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("DROP TABLE IF EXISTS facilities")
    cur.execute("""
        CREATE TABLE facilities (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT,
            lat REAL,
            lon REAL,
            road_addr TEXT,
            lotno_addr TEXT,
            open_hours TEXT,
            tel TEXT,
            extra TEXT
        )
    """)

    cols = ["id", "category", "name", "lat", "lon", "road_addr", "lotno_addr", "open_hours", "tel", "extra"]
    placeholders = ",".join(["?"] * len(cols))
    ins = f"INSERT OR REPLACE INTO facilities ({','.join(cols)}) VALUES ({placeholders})"

    counts = {}
    for gen in (rows_restroom, rows_camping, rows_beach):
        n = 0
        for r in gen():
            cur.execute(ins, [r[c] for c in cols])
            n += 1
        if n:
            counts[gen.__name__.replace("rows_", "")] = n

    # 지오코딩 캐시 재적용 (재빌드 시 좌표 보존)
    restored = apply_geocode_cache(cur)
    if restored:
        print(f"  지오코딩 캐시에서 좌표 복원: {restored:,}건")

    # bounding-box 검색용 인덱스
    cur.execute("CREATE INDEX idx_latlon ON facilities(lat, lon)")
    cur.execute("CREATE INDEX idx_category ON facilities(category)")
    con.commit()

    print("=== facilities.db 빌드 완료 ===")
    for k, v in counts.items():
        print(f"  {k}: {v:,}건")
    # 좌표 유무 통계
    total = cur.execute("SELECT COUNT(*) FROM facilities").fetchone()[0]
    with_coord = cur.execute("SELECT COUNT(*) FROM facilities WHERE lat IS NOT NULL").fetchone()[0]
    print(f"  전체: {total:,}건 / 좌표 있음: {with_coord:,}건 (화장실은 Day2 지오코딩 후 채워짐)")
    con.close()


if __name__ == "__main__":
    main()
