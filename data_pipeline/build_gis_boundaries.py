"""
GIS 경계 데이터 구축 — "이 지점이 규제 구역 안인가?"를 좌표로 판정 (2번 과제)
① 국립공원 경계 23개 (공공데이터포털 국립공원공단 SHP, EPSG:5179)
   → WGS84 GeoJSON 변환 → data/gis/national_parks.geojson
② point_in_park(lat, lon): 순수 파이썬 point-in-polygon (외부 GIS 라이브러리 불필요)
   → 백엔드 /api/zone-check 가 이 GeoJSON을 로드해 사용

원본: data/gis/knps_boundary.zip (data.go.kr 15017313, 로그인 불필요 다운로드)
실행: python data_pipeline/build_gis_boundaries.py   (pyshp·pyproj 필요 — data_pipeline/requirements.txt)
검증: 한라산 백록담(33.3617,126.5292)=한라산 / 제주시청(33.4996,126.5312)=None
"""
import json
from pathlib import Path

import shapefile           # pyshp
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "gis" / "공원경계버퍼" / "BSI_NPK_BBNDR"
OUT = ROOT / "data" / "gis" / "national_parks.geojson"

TR = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)  # Korea2000 UTM-K → WGS84


def convert():
    sf = shapefile.Reader(str(SRC), encoding="cp949")
    feats = []
    for sr in sf.shapeRecords():
        name = sr.record["NPK_NM"]
        pts = sr.shape.points
        parts = list(sr.shape.parts) + [len(pts)]
        rings = []
        for i in range(len(parts) - 1):
            ring = [list(TR.transform(x, y)) for x, y in pts[parts[i]:parts[i + 1]]]
            rings.append([[round(lon, 6), round(lat, 6)] for lon, lat in ring])
        feats.append({"type": "Feature", "properties": {"name": name},
                      "geometry": {"type": "Polygon", "coordinates": rings}})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                              ensure_ascii=False), encoding="utf-8")
    print(f"✅ {len(feats)}개 국립공원 → {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1e6:.1f}MB)")
    return feats


# ── 순수 파이썬 point-in-polygon (ray casting) — 백엔드에서 그대로 재사용 ──
def _in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_park(lat, lon, feats):
    for f in feats:
        rings = f["geometry"]["coordinates"]
        if _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            return f["properties"]["name"]
    return None


if __name__ == "__main__":
    feats = convert()
    tests = [("한라산 백록담", 33.3617, 126.5292), ("제주시청", 33.4996, 126.5312),
             ("지리산 천왕봉", 35.3369, 127.7306), ("서울시청", 37.5665, 126.9780)]
    print("\n=== 판정 테스트 ===")
    for name, lat, lon in tests:
        print(f"  {name} → {point_in_park(lat, lon, feats) or '(공원 밖)'}")
