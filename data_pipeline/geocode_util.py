"""
카카오 지오코딩 유틸 (공용) — 주소검색 + 키워드(장소명)검색
- geocode_address("제주 서귀포시 중문관광로 42")  → 정확한 주소용
- geocode_keyword("새연교")                       → 장소명/랜드마크용 (행사 장소에 적합)
- 반환: (lat, lon) 또는 None
필요: .env 의 KAKAO_REST_KEY
"""
import os
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ADDR = "https://dapi.kakao.com/v2/local/search/address.json"
_KEYWORD = "https://dapi.kakao.com/v2/local/search/keyword.json"


def _load_key():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.startswith("KAKAO_REST_KEY"):
                return line.split("=", 1)[1].split("#")[0].strip()
    return os.environ.get("KAKAO_REST_KEY")


_KEY = _load_key()


def _call(url: str, query: str):
    if not query or not _KEY or "키" in str(_KEY):
        return None
    full = f"{url}?{urllib.parse.urlencode({'query': query})}"
    req = urllib.request.Request(full, headers={"Authorization": f"KakaoAK {_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except Exception:
        return None
    docs = data.get("documents", [])
    if not docs:
        return None
    d = docs[0]
    time.sleep(0.02)
    return (float(d["y"]), float(d["x"]))  # (lat, lon)


def geocode_address(addr: str):
    return _call(_ADDR, addr)


def geocode_keyword(place: str):
    """장소명/랜드마크(예: 새연교, 중문관광단지, 서귀포매일올레시장)"""
    return _call(_KEYWORD, place)


def geocode(place: str):
    """장소명 우선(키워드) → 실패 시 주소검색 폴백"""
    return geocode_keyword(place) or geocode_address(place)


if __name__ == "__main__":
    for q in ["새연교", "중문관광단지", "서귀포매일올레시장"]:
        print(q, "→", geocode_keyword(q))
