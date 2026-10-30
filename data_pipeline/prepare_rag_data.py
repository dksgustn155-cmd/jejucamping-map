"""
RAG 지식베이스용 보조 데이터 준비 (2026-07-06) — 지도 미표시, 파일로만 저장 (팀원 B 사용)
① 전국시티투어 API → data/raw/city_tour.jsonl        (코스 텍스트, RAG 문서)
② LOCALDATA CSV 2종 → theme_park.jsonl / hanok_stay.jsonl
   - 영업중만 필터, 좌표 TM중부(EPSG:2097) → WGS84 변환해 저장
   - 좌표 없거나 범위 밖이면 카카오 지오코딩으로 보완
   - 테마파크 = '아이 동반 놀거리' 추천 재료 / 한옥체험 = 숙박 대안(촌캉스)

실행: python data_pipeline/prepare_rag_data.py
필요: data/raw/문화_일반테마파크업.csv, 문화_한옥체험업.csv (LOCALDATA 다운로드)
"""
import os
import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer
from geocode_util import geocode_address

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# LOCALDATA 좌표계 = TM중부(Bessel, EPSG:2097). 검증: 서울 행촌동 샘플이 실좌표 60m 이내 (5174는 250m 오차)
TM = Transformer.from_crs("EPSG:2097", "EPSG:4326", always_xy=True)
KOREA = (33.0, 38.7, 124.5, 131.0)  # lat_min, lat_max, lon_min, lon_max


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


def in_korea(lat, lon):
    return KOREA[0] <= lat <= KOREA[1] and KOREA[2] <= lon <= KOREA[3]


def tm_to_wgs(x, y):
    try:
        lon, lat = TM.transform(float(x), float(y))
        return (lat, lon) if in_korea(lat, lon) else None
    except (ValueError, TypeError):
        return None


# ── ① 시티투어 (RAG 텍스트) ─────────────────────────────────────────
def city_tour():
    load_env()
    key = os.environ.get("DATA_GO_KR_KEY")
    q = urllib.parse.urlencode({"serviceKey": key, "pageNo": 1, "numOfRows": 1000, "type": "json"})
    url = f"https://api.data.go.kr/openapi/tn_pubr_public_city_tour_api?{q}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    items = data.get("response", {}).get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = [items]
    out = RAW / "city_tour.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps({
                "sido": (it.get("ctprvnNm") or "").strip(),
                "sigungu": (it.get("signguNm") or "").strip(),
                "course_name": (it.get("cityTourCourse") or "").strip(),
                "course_info": (it.get("courseInfo") or "").strip(),
                "boarding": (it.get("brdngPlaceNm") or "").strip(),
                "hours": f"{(it.get('operOpenHhmm') or '').strip()}~{(it.get('operCloseHhmm') or '').strip()}",
                "method": (it.get("operMthd") or "").strip(),
                "tour_info": (it.get("cfrTursmInfo") or "").strip(),
                "phone": (it.get("phoneNumber") or "").strip(),
            }, ensure_ascii=False) + "\n")
    print(f"① 시티투어: {len(items)}건 → {out}")


# ── ② LOCALDATA CSV → 영업중 + WGS84 좌표 ───────────────────────────
def localdata(src_name, out_name, label):
    path = RAW / src_name
    if not path.exists():
        print(f"⚠️ {src_name} 없음 — 건너뜀 (LOCALDATA에서 다운로드해 data/raw/에 두세요)")
        return
    with open(path, encoding="cp949") as f:
        rows = list(csv.reader(f))
    hdr = {c: i for i, c in enumerate(rows[0])}

    def g(r, col):
        i = hdr.get(col)
        return (r[i] if i is not None and len(r) > i else "").strip()

    live = [r for r in rows[1:] if g(r, "영업상태명") in ("영업중", "영업/정상")]
    out, geocoded, dropped = [], 0, 0
    for r in live:
        coord = tm_to_wgs(g(r, "좌표정보(X)"), g(r, "좌표정보(Y)"))
        if not coord:  # 좌표 없음/범위 밖 → 주소 지오코딩
            addr = g(r, "도로명주소") or g(r, "지번주소")
            coord = geocode_address(addr.split("(")[0].strip()) if addr else None
            if coord and not in_korea(*coord):
                coord = None
            if coord:
                geocoded += 1
        if not coord:
            dropped += 1
        out.append({
            "name": g(r, "사업장명"),
            "addr_road": g(r, "도로명주소"),
            "addr_jibun": g(r, "지번주소"),
            "lat": coord[0] if coord else None,
            "lon": coord[1] if coord else None,
            "rooms": g(r, "객실수"),
            "permit_date": g(r, "인허가일자"),
            "type": label,
        })
    out_path = RAW / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    with_coord = sum(1 for o in out if o["lat"])
    jeju = sum(1 for o in out if "제주" in (o["addr_road"] + o["addr_jibun"]))
    print(f"② {label}: 영업중 {len(out)}건 (좌표 {with_coord}, 지오코딩보완 {geocoded}, 좌표실패 {dropped}) · 제주 {jeju} → {out_path}")


if __name__ == "__main__":
    city_tour()
    localdata("문화_일반테마파크업.csv", "theme_park.jsonl", "테마파크")
    localdata("문화_한옥체험업.csv", "hanok_stay.jsonl", "한옥체험")
    print("\n→ RAG 임베딩 소스(팀원 B): city_tour.jsonl · theme_park.jsonl · hanok_stay.jsonl (+festival_std.jsonl, festival.jsonl)")
