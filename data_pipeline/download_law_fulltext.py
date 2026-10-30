"""
법령·조례 원문 다운로드 — 국가법령정보 공동활용 공식 오픈API (open.law.go.kr)
- 공식 출처(casenote 등 미러 대체). .env 의 LAW_GO_KR_OC 사용.
- 흐름: lawSearch.do(검색→일련번호) → lawService.do(본문 XML) → 조문 텍스트 추출 → 저장
- 저장: docs/규정원문/{법령·조례명}.txt (조문번호+내용, RAG 임베딩용)

실행: python data_pipeline/download_law_fulltext.py
OC 발급: open.law.go.kr → 오픈API 신청(무료·즉시) → 마이페이지 'API인증키(OC)'
"""
import os
import re
import html
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "규정원문"
SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE = "https://www.law.go.kr/DRF/lawService.do"

LAWS = [
    "자연공원법", "주차장법", "해수욕장의 이용 및 관리에 관한 법률", "경범죄 처벌법",
    "하천법", "산림보호법", "폐기물관리법", "도로교통법", "도시공원 및 녹지 등에 관한 법률",
    "자연환경보전법",
]
ORDIN_QUERIES = ["제주특별자치도 해수욕장", "제주특별자치도 도시공원", "제주특별자치도 하천"]


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


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _q(**kw):
    return urllib.parse.urlencode({"OC": OC, **kw})


def clean(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


def safe(name):
    return re.sub(r"[^\w가-힣]+", "_", name).strip("_")[:60]


def to_text(body_xml, title):
    """본문 XML → 조문·항·호·목 내용을 문서 순서대로 추출 (호 누락 방지)."""
    parts = [f"# {title}\n(출처: 국가법령정보 공동활용 오픈API, law.go.kr / 다운로드 2026-07-07)\n"]
    units = re.findall(r"<(조문내용|항내용|호내용|목내용)>(.*?)</\1>", body_xml, flags=re.S)
    seen_lines = []
    for _, raw in units:
        t = clean(raw).strip()
        if t and t not in seen_lines[-1:]:  # 바로 위와 동일한 중복만 제거
            seen_lines.append(t)
    if not seen_lines:  # 조문 태그가 없는 짧은 조례 등 폴백
        seen_lines = [clean(body_xml).strip()]
    return "\n".join(parts + seen_lines)


def _pick(xml, tgt_nm, query, exact):
    """검색결과에서 원하는 항목의 (일련번호, 제목) 선택.
    exact=True(법령)면 명칭 완전일치 우선, 아니면(조례) 첫 결과."""
    seqs = re.findall(rf"<{tgt_nm}일련번호>(\d+)</", xml)
    names = re.findall(rf"<{tgt_nm}명(?:한글)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</", xml)
    if not seqs:
        return None, None
    pairs = list(zip(seqs, [clean(n).strip() for n in names]))
    if exact:
        for s, n in pairs:
            if n == query:
                return s, n
    return pairs[0]


def fetch(query, target):
    tgt_nm = "법령" if target == "law" else "자치법규"
    xml = _get(f"{SEARCH}?{_q(target=target, type='XML', query=query, display=20)}")
    seq, title = _pick(xml, tgt_nm, query, exact=(target == "law"))
    if not seq:
        print(f"  ⚠️ '{query}': 검색결과 없음"); return None
    # 법령·조례 모두 본문은 MST(일련번호)로 조회 (조례에 ID 쓰면 '일치 없음' 반환)
    body = _get(f"{SERVICE}?{_q(target=target, type='XML', MST=seq)}")
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{safe(title)}.txt"
    p.write_text(to_text(body, title), encoding="utf-8")
    print(f"  ✅ {title} → {p.relative_to(ROOT)} ({p.stat().st_size:,}B)")
    return title


def main():
    if not OC or "여기에" in str(OC):
        print("⚠️ .env 에 LAW_GO_KR_OC 없음. open.law.go.kr에서 무료 OC 발급 후 추가."); return
    print("=== 국가법률 ===")
    seen = set()
    for n in LAWS:
        if n in seen:
            continue
        seen.add(n)
        fetch(n, "law")
    print("=== 제주 조례(자치법규) ===")
    for n in ORDIN_QUERIES:
        fetch(n, "ordin")
    print(f"\n저장 위치: {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
