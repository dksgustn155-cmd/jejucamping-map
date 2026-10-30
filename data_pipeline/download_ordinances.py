"""
전국 지자체 캠핑 조례 수집 (국가법령정보 공식 오픈API, target=ordin) — RAG용
- 범위: 캠핑 직결 키워드(오토캠핑·야영장·캠핑장·해수욕장)로 검색된 조례만
- 본문 필터: 야영/취사/차박/차량/금지/과태료 포함된 것만 저장 (노이즈 제거)
- 지역 태그(지자체기관명) 부착 → 챗봇이 사용자 지역 조례를 골라 검색 가능
- 저장: data/raw/ordinances.jsonl (RAG), 요약은 콘솔 + docs/규정원문/조례_INDEX.md

실행: python data_pipeline/download_ordinances.py
필요: .env 의 LAW_GO_KR_OC
"""
import os
import re
import html
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "ordinances.jsonl"
INDEX = ROOT / "docs" / "규정원문" / "조례_INDEX.md"
SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE = "https://www.law.go.kr/DRF/lawService.do"

KEYWORDS = ["오토캠핑", "야영장", "캠핑장", "해수욕장"]
# 본문에 이 중 하나라도 있어야 저장 (실제 캠핑·규제 관련성 확인)
KEEP = re.compile(r"야영|취사|차박|차량|캠핑|금지|과태료")
# 규제형(금지·과태료) 여부 태그용
RESTRICT = re.compile(r"취사|차박|금지|제한|과태료|불을")


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
OC = os.environ.get("LAW_GO_KR_OC")


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.0)


def _q(**kw):
    return urllib.parse.urlencode({"OC": OC, **kw})


def clean(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()


def field(block, tag):
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S)
    return m.group(1).strip() if m else ""


def search_all(keyword):
    """키워드로 전국 조례 목록 페이지네이션 수집."""
    items, page = [], 1
    while page <= 30:
        xml = _get(f"{SEARCH}?{_q(target='ordin', type='XML', query=keyword, display=100, page=page)}")
        total = int(re.search(r"<totalCnt>(\d+)</totalCnt>", xml).group(1) or 0)
        blocks = re.findall(r"<law>.*?</law>", xml, re.S) or re.split(r"(?=<자치법규일련번호>)", xml)[1:]
        for b in blocks:
            seq = field(b, "자치법규일련번호")
            if seq:
                items.append({"seq": seq, "name": clean(field(b, "자치법규명")),
                              "org": clean(field(b, "지자체기관명")), "field": clean(field(b, "자치법규분야명")),
                              "date": field(b, "시행일자")})
        if page * 100 >= total or not blocks:
            break
        page += 1
        time.sleep(0.2)
    return items


def body_text(seq):
    xml = _get(f"{SERVICE}?{_q(target='ordin', type='XML', MST=seq)}")
    if "일치하는" in xml[:200]:
        return None
    units = re.findall(r"<(조문내용|항내용|호내용|목내용)>(.*?)</\1>", xml, re.S)
    text = "\n".join(clean(u[1]) for u in units if clean(u[1]))
    return text or clean(xml)


def main():
    if not OC:
        print("⚠️ .env 에 LAW_GO_KR_OC 없음"); return
    # 1) 목록 수집 + 중복 제거
    seen, cand = set(), []
    for kw in KEYWORDS:
        got = search_all(kw)
        new = [x for x in got if x["seq"] not in seen]
        seen.update(x["seq"] for x in new)
        cand += new
        print(f"검색 '{kw}': {len(got)}건 (신규 {len(new)}, 누적 {len(cand)})")

    # 2) 본문 다운로드 + 필터
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows, kept, restrict = [], 0, 0
    for i, c in enumerate(cand, 1):
        try:
            body = body_text(c["seq"])
        except Exception as e:
            print(f"  ! {c['name']} 실패: {e}"); continue
        if not body or not KEEP.search(body):
            continue
        r = {"id": f"ordin:{c['seq']}", "지자체": c["org"], "조례명": c["name"],
             "분야": c["field"], "시행일": c["date"],
             "규제형": bool(RESTRICT.search(body)), "원문": body}  # 전문(컷 없음)
        rows.append(r); kept += 1; restrict += r["규제형"]
        if i % 40 == 0:
            print(f"  ...{i}/{len(cand)} 처리 (저장 {kept})")
        time.sleep(0.25)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 3) 인덱스 (지자체별 요약)
    from collections import Counter
    by_org = Counter(r["지자체"] for r in rows)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(f"# 전국 캠핑 조례 인덱스 ({kept}건, 규제형 {restrict}건)\n\n")
        f.write("> 공식 오픈API(law.go.kr, target=ordin) 수집 · 원문은 `data/raw/ordinances.jsonl`\n\n")
        f.write("| 지자체 | 조례 수 |\n|---|---|\n")
        for org, n in by_org.most_common():
            f.write(f"| {org} | {n} |\n")

    print(f"\n✅ 저장 {kept}건 (규제형 {restrict}) · 지자체 {len(by_org)}곳 → {OUT}")
    print(f"   인덱스 → {INDEX}")


if __name__ == "__main__":
    main()
