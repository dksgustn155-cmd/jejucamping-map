"""빈터(노지) 후보 배치 수집 — V-World 연속지적도 + 토지소유 + 토지특성 (제주 전역).

로직(격자별 증분 처리 — 중단돼도 재실행하면 처음부터 다시):
  1) 격자마다 연속지적도(LP_PA_CBND_BUBUN) WFS → 지목 '잡종지'(잡) 필지 + '묘지'(묘) 위치 수집
  2) 토지소유정보(getPossessionAttr): 개인·법인·종중·외국·종교 제외 → 공공/기타단체만
  3) 토지특성(getLandCharacteristics): **맹지(도로없음)·급경사·실제이용중(과수원·주거·상업 등) 제외**
  4) 근처 150m 내 묘지(혐오시설) 있으면 제외
  5) 주변 건물수(한적함) 계산 → facilities.db category='nakji' insert + nakji.jsonl

주의: V-World 무료 일 한도(~4만) throttle. 제주 전역은 수 시간 소요. build_db 재생성 시 nakji 소멸 → 재실행.
"""
import json
import math
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_JSONL = ROOT / "data" / "raw" / "nakji.jsonl"

REGION_BBOX = (33.19, 126.14, 33.57, 126.98)  # 제주 본섬 전역
CELL = 0.012  # ~1.3km

EXCLUDE_OWNERS = ("개인", "법인", "종중", "외국", "종교")            # 사유지성 → 제외
BAD_USE = re.compile(r"과수원|답|주거|상업|공장|축사|목장|묘|사찰|골프|발전|주유|창고")  # 실이용 → 제외
BAD_SLOPE = ("급경사", "고지", "험준")                              # 지형 → 제외
GRAVE_MIN_M = 150  # 묘지 최소 이격


def _load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _dist(la1, lo1, la2, lo2):
    R, rad = 6371000.0, math.pi / 180
    dla, dlo = (la2 - la1) * rad, (lo2 - lo1) * rad
    a = math.sin(dla / 2) ** 2 + math.cos(la1 * rad) * math.cos(la2 * rad) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _centroid(geom):
    coords, g = [], geom.get("coordinates") or []
    polys = g if geom.get("type") == "MultiPolygon" else [g]
    for poly in polys:
        if poly and poly[0]:
            coords.extend(poly[0])
    if not coords:
        return None
    return sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)


def _jimok(jibun):
    s = (jibun or "").strip()
    return s[-1] if s else ""


def _owner(vkey, pnu):
    url = (f"https://api.vworld.kr/ned/data/getPossessionAttr?key={vkey}&pnu={pnu}"
           "&format=json&numOfRows=1&domain=localhost")
    try:
        fields = (_get(url, 12).get("possessions") or {}).get("field") or []
        return (fields[0].get("posesnSeCodeNm") or "").strip() if fields else ""
    except Exception:  # noqa: BLE001
        return ""


def _landchar(vkey, pnu):
    """토지특성: 도로접면·지형·실이용상황. 맹지/급경사/실이용이면 부적합."""
    url = (f"https://api.vworld.kr/ned/data/getLandCharacteristics?key={vkey}&pnu={pnu}"
           "&format=json&numOfRows=1&domain=localhost&stdrYear=2024")
    try:
        fields = (_get(url, 12).get("landCharacteristicss") or {}).get("field") or []
        return fields[0] if fields else {}
    except Exception:  # noqa: BLE001
        return {}


def _house_count(vkey, lat, lon, radius_m=250):
    dlat = radius_m / 111000.0
    dlon = radius_m / (111000.0 * math.cos(lat * math.pi / 180) or 1)
    box = urllib.parse.quote(f"BOX({lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat})")
    url = ("https://api.vworld.kr/req/data?service=data&request=GetFeature&version=2.0"
           f"&data=LT_C_SPBD&format=json&size=1000&crs=EPSG:4326&domain=localhost&geomFilter={box}&key={vkey}")
    try:
        resp = _get(url, 10).get("response", {})
        if resp.get("status") != "OK":
            return None
        total = (resp.get("record") or {}).get("total")
        return int(total) if total is not None else None
    except Exception:  # noqa: BLE001
        return None


def _cells():
    minlat, minlon, maxlat, maxlon = REGION_BBOX
    out, lat = [], minlat
    while lat < maxlat:
        lon = minlon
        while lon < maxlon:
            out.append((lon, lat, min(lon + CELL, maxlon), min(lat + CELL, maxlat)))
            lon += CELL
        lat += CELL
    return out


def _reject(lc, lat, lon, graves):
    """부적합 사유 반환 (None이면 통과)."""
    road = lc.get("roadSideCodeNm") or ""
    slope = lc.get("tpgrphHgCodeNm") or ""
    use = lc.get("ladUseSittnNm") or ""
    if "맹지" in road:
        return "맹지(도로없음)"
    if any(s in slope for s in BAD_SLOPE):
        return f"급경사({slope})"
    if use and BAD_USE.search(use):
        return f"실이용({use})"
    for gla, glo in graves:
        if _dist(lat, lon, gla, glo) <= GRAVE_MIN_M:
            return "묘지 인접"
    return None


def scan(vkey):
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='nakji'")  # 필터 바뀌었으니 새로
    con.commit()
    jf = open(OUT_JSONL, "w", encoding="utf-8")
    cells = _cells()
    print(f"제주 전역 격자 {len(cells)}칸 · 맹지·급경사·실이용·묘지인접 제외하고 수집")
    graves, kept, checked = [], 0, 0
    for ci, (minx, miny, maxx, maxy) in enumerate(cells, 1):
        box = urllib.parse.quote(f"BOX({minx},{miny},{maxx},{maxy})")
        page, jabs = 1, []
        while True:
            url = ("https://api.vworld.kr/req/data?service=data&request=GetFeature&version=2.0"
                   f"&data=LP_PA_CBND_BUBUN&format=json&size=1000&page={page}&crs=EPSG:4326"
                   f"&domain=localhost&geomFilter={box}&key={vkey}")
            try:
                feats = (((_get(url).get("response") or {}).get("result") or {}).get("featureCollection") or {}).get("features") or []
            except Exception:  # noqa: BLE001
                break
            for f in feats:
                jm = _jimok(f["properties"].get("jibun"))
                c = _centroid(f.get("geometry") or {})
                if not c:
                    continue
                if jm == "묘":  # 묘지 위치 축적 (혐오시설 이격용)
                    graves.append((c[1], c[0]))
                elif jm == "잡":
                    p = f["properties"]
                    jabs.append({"pnu": p.get("pnu"), "addr": p.get("addr"), "lon": c[0], "lat": c[1]})
            if len(feats) < 1000:
                break
            page += 1
            time.sleep(0.1)
        for c in jabs:
            checked += 1
            own = _owner(vkey, c["pnu"]); time.sleep(0.12)
            if not own or any(x in own for x in EXCLUDE_OWNERS):
                continue
            lc = _landchar(vkey, c["pnu"]); time.sleep(0.12)
            bad = _reject(lc, c["lat"], c["lon"], graves)
            if bad:
                continue
            houses = _house_count(vkey, c["lat"], c["lon"]); time.sleep(0.12)
            name = (c.get("addr") or "").split()[-1] if c.get("addr") else c["pnu"]
            row = {**c, "owner": own, "houses": houses,
                   "road": lc.get("roadSideCodeNm"), "slope": lc.get("tpgrphHgCodeNm"), "use": lc.get("ladUseSittnNm")}
            con.execute(
                "INSERT OR REPLACE INTO facilities (id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"nakji:{c['pnu']}", "nakji", name, c["lat"], c["lon"], "", c.get("addr") or "", "", "",
                 json.dumps({"jimok": "잡종지", "owner": own, "pnu": c["pnu"], "houses": houses,
                             "road": lc.get("roadSideCodeNm"), "slope": lc.get("tpgrphHgCodeNm"),
                             "use": lc.get("ladUseSittnNm")}, ensure_ascii=False)))
            jf.write(json.dumps(row, ensure_ascii=False) + "\n"); jf.flush()
            kept += 1
        if ci % 20 == 0:
            con.commit()
            print(f"  격자 {ci}/{len(cells)} · 잡종지검토 {checked} · 통과 빈터 {kept} · 묘지 {len(graves)}")
    con.commit(); con.close(); jf.close()
    return kept


def main():
    _load_env()
    vkey = os.environ.get("VWORLD_KEY", "").strip()
    if not vkey:
        raise SystemExit("VWORLD_KEY 없음")
    t0 = time.time()
    kept = scan(vkey)
    print(f"[완료] 제주 전역 적합 빈터 {kept}곳 ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
