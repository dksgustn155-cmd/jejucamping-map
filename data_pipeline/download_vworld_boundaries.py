"""
브이월드 WFS로 자연공원 경계 확장 수집 — 도립·군립공원 (자연공원법 동일 적용)
- 국립공원(national_parks.geojson, 공공데이터포털)에 더해 도립·군립까지 좌표 판정 확대
- WFS 2.0 GetFeature → GeoJSON, EPSG:4326 직접 수신 (변환 불필요)
- 저장: data/gis/natural_parks_vworld.geojson (properties: name, kind)
- /api/zone-check 가 국립+도립+군립을 모두 로드해 판정

실행: python data_pipeline/download_vworld_boundaries.py
필요: .env 의 VWORLD_KEY (개발키, 만료 2027-01-08 — 만료 전 연장)
레이어: lt_c_wgisnpdo(도립) · lt_c_wgisnpgun(군립)  [국립 lt_c_wgisnpgug 은 공공데이터포털본 사용]
"""
import os
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gis" / "natural_parks_vworld.geojson"
WFS = "https://api.vworld.kr/req/wfs"

LAYERS = [("lt_c_wgisnpdo", "도립공원"), ("lt_c_wgisnpgun", "군립공원")]


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
KEY = os.environ.get("VWORLD_KEY")


def fetch_layer(typename, kind):
    """STARTINDEX 페이지네이션으로 레이어 전체 수집."""
    feats, start = [], 0
    while True:
        q = urllib.parse.urlencode({
            "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
            "TYPENAME": typename, "SRSNAME": "EPSG:4326",
            "OUTPUT": "application/json", "MAXFEATURES": 500, "STARTINDEX": start,
            "KEY": KEY, "DOMAIN": "localhost",
        })
        with urllib.request.urlopen(f"{WFS}?{q}", timeout=90) as r:
            d = json.load(r)
        got = d.get("features", [])
        if not got:
            break
        for f in got:
            name = (f.get("properties", {}).get("park_name") or "").strip()
            geom = f.get("geometry")
            if not geom:
                continue
            feats.append({"type": "Feature",
                          "properties": {"name": name or typename, "kind": kind},
                          "geometry": _round_geom(geom)})
        if len(got) < 500:
            break
        start += 500
        time.sleep(0.3)
    print(f"  {kind}({typename}): {len(feats)}개")
    return feats


def _round_geom(geom, nd=6):
    def rec(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [rec(x) for x in c]
    return {"type": geom["type"], "coordinates": rec(geom["coordinates"])}


def main():
    if not KEY:
        print("⚠️ .env 에 VWORLD_KEY 없음"); return
    all_feats = []
    for typename, kind in LAYERS:
        all_feats += fetch_layer(typename, kind)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": all_feats},
                              ensure_ascii=False), encoding="utf-8")
    print(f"✅ 도립·군립 {len(all_feats)}개 → {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1e6:.1f}MB)")


if __name__ == "__main__":
    main()
