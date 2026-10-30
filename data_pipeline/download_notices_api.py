"""
고시·금지구역 자동 수집기 (국가법령정보 공식 오픈API) — 재실행 가능한 자동화
- ① 행정규칙(target=admrul): 중앙부처·해경 등의 고시 — 금지구역·출입통제·습지·해수욕장 등
- ② 자치법규(target=ordin) 보강: '낚시·금지구역·차박·글램핑' 키워드 조례 중
     캠핑 관련(야영·취사·캠핑·차박) 본문만 — 기존 ordinances.jsonl 이 못 잡던
     '하천 낚시·야영·취사 금지구역 지정' 계열을 흡수
- 저장: data/raw/notices_api.jsonl (전문 포함, 재실행 시 전체 재생성=최신화)
- 수동 수집분(data/raw/notices.jsonl)과 별도 파일 — 둘 다 RAG 소스

실행: python data_pipeline/download_notices_api.py
자동화: refresh 배치에 포함 가능(주 1회). 필요: .env 의 LAW_GO_KR_OC
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
OUT = ROOT / "data" / "raw" / "notices_api.jsonl"
SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE = "https://www.law.go.kr/DRF/lawService.do"

# ① 행정규칙 키워드 (제목 검색) — 스캔으로 유효 확인된 것
ADMRUL_KW = ["금지구역", "출입통제", "통제구역", "수상레저", "해수욕장",
             "습지", "출입제한", "야영", "하천 점용"]
# ② 조례 보강 키워드 (기존 ordinances 키워드에 없던 것)
ORDIN_KW = ["낚시", "금지구역", "차박", "글램핑"]

# 본문 관련성 필터
ADMRUL_KEEP = re.compile(r"야영|취사|캠핑|차박|출입\s?금지|출입\s?통제|금지구역|갯벌|해수욕장|물놀이|습지")
ORDIN_KEEP = re.compile(r"야영|취사|캠핑|차박")   # 조례 보강은 캠핑 직결만 (낚시 전용 제외)


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
        except Exception:
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
    return clean(m.group(1)) if m else ""


def search_all(target, keyword, name_tag, seq_tag):
    items, page = [], 1
    while page <= 20:
        xml = _get(f"{SEARCH}?{_q(target=target, type='XML', query=keyword, display=100, page=page)}")
        total = int(re.search(r"<totalCnt>(\d+)</totalCnt>", xml).group(1) or 0)
        blocks = re.split(rf"(?=<{seq_tag}>)", xml)[1:]
        for b in blocks:
            seq = field(b, seq_tag)
            if seq:
                items.append({"seq": seq, "name": field(b, name_tag),
                              "org": field(b, "소관부처명") or field(b, "지자체기관명"),
                              "kind": field(b, "행정규칙종류") or field(b, "자치법규종류"),
                              "date": field(b, "발령일자") or field(b, "시행일자"),
                              "kw": keyword})
        if page * 100 >= total or not blocks:
            break
        page += 1
        time.sleep(0.2)
    return items


def body_text(target, seq):
    """본문: MST 우선, 실패 시 ID (조례에서 배운 교훈)."""
    for param in ("MST", "ID"):
        xml = _get(f"{SERVICE}?{_q(target=target, type='XML', **{param: seq})}")
        if "일치하는" in xml[:300]:
            continue
        units = re.findall(r"<(조문내용|항내용|호내용|목내용|개정문내용|첨부내용)>(.*?)</\1>", xml, re.S)
        text = "\n".join(clean(u[1]) for u in units if clean(u[1]))
        return text if len(text) > 80 else clean(xml)
    return None


def collect(target, keywords, keep, label):
    seen, out = set(), []
    name_tag = "행정규칙명" if target == "admrul" else "자치법규명"
    seq_tag = "행정규칙일련번호" if target == "admrul" else "자치법규일련번호"
    for kw in keywords:
        got = search_all(target, kw, name_tag, seq_tag)
        new = [x for x in got if x["seq"] not in seen]
        seen.update(x["seq"] for x in new)
        print(f"  검색[{label}] '{kw}': {len(got)}건 (신규 {len(new)})")
        for c in new:
            try:
                body = body_text(target, c["seq"])
            except Exception as e:
                print(f"    ! {c['name'][:30]} 실패: {e}"); continue
            if not body or not keep.search(c["name"] + body):
                continue
            out.append({"id": f"{target}:{c['seq']}", "구분": label,
                        "명칭": c["name"], "기관": c["org"], "종류": c["kind"],
                        "발령/시행일": c["date"], "검색키워드": c["kw"], "원문": body})
            time.sleep(0.25)
    return out


def main():
    if not OC:
        print("⚠️ .env 에 LAW_GO_KR_OC 없음"); return
    print("=== ① 행정규칙(고시·지침) ===")
    admrul = collect("admrul", ADMRUL_KW, ADMRUL_KEEP, "행정규칙(고시)")
    print(f"  → 저장 대상 {len(admrul)}건")
    print("=== ② 조례 보강(낚시·금지구역 계열 중 캠핑 관련) ===")
    ordin = collect("ordin", ORDIN_KW, ORDIN_KEEP, "조례(금지구역)")
    print(f"  → 저장 대상 {len(ordin)}건")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in admrul + ordin:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n✅ notices_api.jsonl 저장: 행정규칙 {len(admrul)} + 조례보강 {len(ordin)} = {len(admrul)+len(ordin)}건 → {OUT}")


if __name__ == "__main__":
    main()
