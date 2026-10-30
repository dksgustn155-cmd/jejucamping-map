"""
제주 행사·축제 '소식(뉴스)' 수집 + 지오코딩 (뼈대)
- 소스: https://www.jeju.go.kr/api/jejutoseoul/festival/ (키 불필요, 끝 슬래시 필수)
- 흐름: ① fetch(뉴스 텍스트) → ② 구조화 추출 → ③ 장소 지오코딩 → ④ category='festival_news' DB
- ⚠️ 2026-07-06부터 지도 메인 축제 레이어는 전국문화축제표준(collect_festival_std.py, category='festival').
  이 스크립트는 제주 '소식' 보완용: 원문 jsonl=RAG + GPT 추출(이슈 #12) 후 festival_news로 저장(지도 미표시)

⚠️ ② 구조화 추출은 현재 **GPT 스텁**입니다:
   - GPT mini 키 도착(수요일) 후 extract_with_gpt() 를 채우면 완성
   - 지금은 --naive 플래그로 "제목을 장소로 간주하고 지오코딩" (대략적, 데모/뼈대 검증용)
   - 원문 텍스트는 별도로 RAG 지식베이스(이슈 #3)에도 사용

실행:
   python data_pipeline/collect_festival.py          # fetch + jsonl 저장(좌표 없음, 원문 보존)
   python data_pipeline/collect_festival.py --naive   # 제목 지오코딩까지 시도해 지도 마커 생성(임시)
"""
import re
import sys
import json
import sqlite3
import urllib.request
from pathlib import Path

from geocode_util import geocode  # 같은 폴더

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
OUT_PATH = ROOT / "data" / "raw" / "festival.jsonl"
URL = "https://www.jeju.go.kr/api/jejutoseoul/festival/"


# 제주도 좌표 범위 — 키워드 검색은 전국 대상이라 동명 장소(예: 서울 전농로)가
# 다른 지역에 잡힐 수 있음. 범위 밖 좌표는 버림 (GPT 연결 후에도 필요한 안전장치)
JEJU_BBOX = (33.1, 33.7, 126.08, 127.0)  # lat_min, lat_max, lon_min, lon_max


def in_jeju(coord) -> bool:
    if not coord:
        return False
    lat, lon = coord
    return JEJU_BBOX[0] <= lat <= JEJU_BBOX[1] and JEJU_BBOX[2] <= lon <= JEJU_BBOX[3]


def fetch_posts() -> list:
    posts, seen, page = [], set(), 1
    while page <= 20:  # 안전 상한 (API가 페이지 파라미터를 무시해도 무한루프 방지)
        with urllib.request.urlopen(f"{URL}?pageNo={page}&pageSize=100", timeout=30) as r:
            data = json.load(r)
        items = [i for i in data.get("items", []) if i.get("seq") not in seen]
        if not items:
            break
        posts += items
        seen |= {i.get("seq") for i in items}
        if len(posts) >= int(data.get("total", 0)):
            break
        page += 1
    return posts


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_with_gpt(post: dict) -> dict:
    """[TODO: GPT mini 키 도착 후 구현]
    입력: post(title, contents) → 출력: {name, place, period, summary}
    프롬프트 규칙(환각 방지): 본문에 명시된 장소만, 추측 금지, 없으면 place=null.
    지금은 미구현 → place=None 반환 (지도에 안 찍힘)."""
    return {"name": post.get("title", "").strip(), "place": None, "period": None,
            "summary": strip_html(post.get("contents", ""))[:200]}


def naive_place_guess(title: str) -> str:
    """임시 장소 추출(GPT 대체): 연도·따옴표블록 제거 후 앞 1~2어절.
    예) '2025 새연교 주말 문화공연 『금토금토 새연쇼』' → '새연교'
    부정확 — GPT extract_with_gpt() 로 대체될 자리."""
    t = re.sub(r"20\d\d", "", title or "")           # 연도 제거
    t = re.sub(r"[『「【\[(].*", "", t)               # 따옴표/괄호 블록부터 뒤 잘라냄
    t = re.sub(r"제?\s*\d+\s*회", "", t)              # 'N회' 제거
    words = [w for w in t.split() if w]
    if not words:
        return ""
    # 앞 1어절이 지역명(제주/서귀포/제주시)뿐이면 2어절까지
    region = {"제주", "제주시", "서귀포", "서귀포시"}
    return " ".join(words[:2]) if words[0] in region and len(words) > 1 else words[0]


def extract_naive(post: dict) -> dict:
    """임시: 제목에서 장소 후보 추출해 지오코딩 (GPT 전 뼈대 검증용)"""
    info = extract_with_gpt(post)
    info["place"] = naive_place_guess(post.get("title", ""))
    return info


def main(naive: bool):
    posts = fetch_posts()
    print(f"행사 소식: {len(posts)}건 fetch")

    extract = extract_naive if naive else extract_with_gpt
    rows = []
    for p in posts:
        info = extract(p)
        coord = geocode(info["place"]) if info.get("place") else None
        if coord and not in_jeju(coord):
            coord = None  # 동명 장소가 육지에 잡힌 것 — 좌표 폐기 (원문은 jsonl에 보존)
        rows.append({
            "id": f"festival:{p.get('seq')}",
            "name": info["name"], "place": info["place"],
            "period": info["period"], "summary": info["summary"],
            "url": p.get("url"), "writeDate": p.get("writeDate"),
            "lat": coord[0] if coord else None,
            "lon": coord[1] if coord else None,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with_coord = [r for r in rows if r["lat"] is not None]
    print(f"저장: {len(rows)}건 (좌표 확보 {len(with_coord)}) → {OUT_PATH}")

    # DB 반영 (좌표 있는 것만 지도 마커로)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("DELETE FROM facilities WHERE category='festival_news'")
    for r in with_coord:
        con.execute(
            "INSERT OR REPLACE INTO facilities "
            "(id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "festival_news", r["name"], r["lat"], r["lon"], r["place"] or "", "", "", "",
             json.dumps({"period": r["period"], "summary": r["summary"], "url": r["url"]},
                        ensure_ascii=False)))
    con.commit()
    con.close()
    print(f"DB 반영: festival {len(with_coord)}건" + (" (naive 제목 지오코딩)" if naive else " (GPT 미연결이라 0)"))
    if not naive:
        print("→ GPT mini 키 연결 후 extract_with_gpt() 구현하면 정확한 장소로 채워짐 (이슈 #12)")


if __name__ == "__main__":
    main(naive="--naive" in sys.argv)
