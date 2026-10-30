"""제주 주차장(공영·둔치) 주변 건물수(민가) 사전계산 — V-World 건물레이어(LT_C_SPBD).

목적: 민가 많은 주차장은 지도·추천·조회에서 제외하기 위해, 각 주차장 좌표의 주변 건물수를
      계산해 facilities.db 의 extra.houses 에 저장. backend 는 houses > PARKING_HOUSE_MAX(40) 를 배제.

로직(증분·재실행 가능):
  1) 제주 bbox 내 category in (parking_public, parking) 중 extra.houses 없는 행만 선택
  2) recommend.house_count(lat, lon) 로 반경 250m 건물수 조회 (V-World 실패 시 None → 다음 실행에 재시도)
  3) extra.houses 채워 UPDATE, 20건마다 커밋

주의: V-World 무료 일 한도(~4만) throttle. 제주 주차장 ~1,600곳이라 수 분~십수 분.
      nakji 배치와 동시에 돌리면 V-World rate limit 충돌하니 순차 실행할 것.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
REGION_BBOX = (33.19, 126.14, 33.57, 126.98)  # 제주 본섬 전역


def _load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())


def main():
    _load_env()
    os.environ["SSL_CERT_FILE"] = certifi.where()  # 이 PC SSL_CERT_FILE 깨져 있어 certifi 로 교정
    sys.path.insert(0, str(ROOT))
    from backend.recommend import house_count   # V-World LT_C_SPBD 건물수 (캐시 포함)

    sa, so, na, no = REGION_BBOX
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, lat, lon, extra FROM facilities "
        "WHERE category IN ('parking_public','parking') "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", (sa, na, so, no)).fetchall()
    todo = []
    for r in rows:
        ex = json.loads(r["extra"]) if r["extra"] else {}
        if ex.get("houses") is None:           # 아직 계산 안 된 것만
            todo.append((r["id"], r["lat"], r["lon"], ex))
    print(f"제주 주차장 {len(rows)}곳 중 미계산 {len(todo)}곳 처리 시작")

    done = fail = 0
    for i, (fid, lat, lon, ex) in enumerate(todo, 1):
        n = house_count(lat, lon)              # None 이면 이번엔 스킵(다음 실행에 재시도)
        if n is None:
            fail += 1
            continue
        ex["houses"] = n
        con.execute("UPDATE facilities SET extra=? WHERE id=?",
                    (json.dumps(ex, ensure_ascii=False), fid))
        done += 1
        if i % 20 == 0:
            con.commit()
            print(f"  {i}/{len(todo)} · 저장 {done} · 조회실패 {fail}")
        time.sleep(0.05)                       # V-World throttle 완화
    con.commit()
    # 요약: 임계값 초과(배제 대상) 몇 곳인지
    over = con.execute(
        "SELECT COUNT(*) FROM facilities WHERE category IN ('parking_public','parking') "
        "AND CAST(json_extract(extra,'$.houses') AS INTEGER) > 40").fetchone()[0]
    have = con.execute(
        "SELECT COUNT(*) FROM facilities WHERE category IN ('parking_public','parking') "
        "AND json_extract(extra,'$.houses') IS NOT NULL "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", (sa, na, so, no)).fetchone()[0]
    con.close()
    print(f"✅ 완료 · 저장 {done} · 조회실패 {fail}(다음 실행에 재시도) · "
          f"houses 보유 {have}곳 · 40채 초과(배제) {over}곳")


if __name__ == "__main__":
    main()
