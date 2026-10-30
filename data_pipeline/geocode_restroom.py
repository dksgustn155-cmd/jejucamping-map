"""
화장실 주소 → 좌표 지오코딩 (카카오 로컬 API) — v2 병렬 버전
- 개선점 (2026-07-06):
  1. 병렬 처리(5 workers): 순차 방식은 5시간 → 병렬로 남은 분량 15~20분
  2. 고유 주소 단위로 호출 (같은 주소 여러 화장실 중복 호출 제거)
  3. 시작 시 기존 캐시를 DB에 먼저 반영 (중단 후 재개 시 즉시 복구)
  4. 일시 오류(쿼터/네트워크)는 캐시하지 않음 → 재실행 시 재시도
- 캐시: data/raw/geocode_cache.json (성공 좌표 + 진짜 결과없음(None)만 저장)

실행: python data_pipeline/geocode_restroom.py [최대주소수]
필요: .env 의 KAKAO_REST_KEY
"""
import os
import json
import time
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
CACHE_PATH = ROOT / "data" / "raw" / "geocode_cache.json"

WORKERS = 5        # 동시 요청 수 (카카오 한도 안전선)
CHUNK = 500        # 청크 단위로 캐시/DB 저장 (중단 안전)


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
REST_KEY = os.environ.get("KAKAO_REST_KEY")
assert REST_KEY and "키" not in REST_KEY, ".env 에 KAKAO_REST_KEY 를 설정하세요"

GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"
ERROR = "ERROR"  # 일시적 실패 표식 — 캐시에 저장하지 않음


def geocode(address: str):
    """주소 → (lat, lon) / None(진짜 결과없음) / ERROR(일시 오류)"""
    if not address:
        return None
    url = f"{GEOCODE_URL}?{urllib.parse.urlencode({'query': address})}"
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {REST_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except Exception:
        return ERROR
    docs = data.get("documents", [])
    if not docs:
        return None
    d = docs[0]
    time.sleep(0.02)  # 워커당 살짝 간격 (전체 ~25 rps 이하 유지)
    return (float(d["y"]), float(d["x"]))  # (위도, 경도)


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict):
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_PATH)  # 원자적 저장 (중단돼도 캐시 파일 안 깨짐)


def apply_cache_to_db(con, addr_rows: dict, cache: dict) -> int:
    """캐시에 있는 좌표를 DB의 NULL 화장실에 반영"""
    n = 0
    for addr, ids in addr_rows.items():
        coord = cache.get(addr)
        if coord:
            for fid in ids:
                con.execute("UPDATE facilities SET lat=?, lon=? WHERE id=?",
                            (coord[0], coord[1], fid))
                n += 1
    con.commit()
    return n


def main(limit: int | None = None):
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    con.row_factory = sqlite3.Row

    # 좌표 없는 화장실 → 고유 주소별로 묶기
    addr_rows: dict[str, list] = {}
    for row in con.execute(
        "SELECT id, road_addr, lotno_addr FROM facilities "
        "WHERE category='restroom' AND lat IS NULL"
    ):
        addr = (row["road_addr"] or row["lotno_addr"] or "").strip()
        if addr:
            addr_rows.setdefault(addr, []).append(row["id"])

    cache = load_cache()

    # 1) 기존 캐시 먼저 반영 (재개 시 즉시 복구)
    restored = apply_cache_to_db(con, addr_rows, cache)
    if restored:
        print(f"캐시에서 좌표 복원: {restored:,}건")

    # 2) 아직 시도 안 한 고유 주소만 병렬 지오코딩
    todo = [a for a in addr_rows if a not in cache]
    if limit:
        todo = todo[:limit]
    print(f"지오코딩 대상: 고유 주소 {len(todo):,}개 (화장실 {sum(len(addr_rows[a]) for a in todo):,}건)")

    hit = miss = errs = 0
    for start in range(0, len(todo), CHUNK):
        chunk = todo[start:start + CHUNK]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(geocode, chunk))

        chunk_errs = 0
        for addr, coord in zip(chunk, results):
            if coord == ERROR:
                chunk_errs += 1
                continue          # 캐시 안 함 → 다음 실행에서 재시도
            cache[addr] = coord   # 좌표 or None(결과없음)
            if coord:
                hit += 1
                for fid in addr_rows[addr]:
                    con.execute("UPDATE facilities SET lat=?, lon=? WHERE id=?",
                                (coord[0], coord[1], fid))
            else:
                miss += 1

        errs += chunk_errs
        con.commit()
        save_cache(cache)
        print(f"  {min(start+CHUNK, len(todo)):,}/{len(todo):,} 주소 (성공 {hit:,} / 결과없음 {miss:,} / 오류 {errs:,})")

        if chunk_errs > CHUNK * 0.5:  # 청크 절반 이상 오류 = 쿼터 소진/네트워크 장애로 판단
            print("오류율 과다 — 중단합니다. 다음 실행 시 이어서 재시도됩니다.")
            break

    done = con.execute(
        "SELECT COUNT(*) FROM facilities WHERE category='restroom' AND lat IS NOT NULL"
    ).fetchone()[0]
    con.close()
    print(f"완료 — 좌표 확보 화장실 총 {done:,} / 59,768")


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=limit)
