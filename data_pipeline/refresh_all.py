"""
전체 정적 데이터 일괄 갱신 (Tier 1) — 월 1회 실행용 오케스트레이터
- 수집 → DB 재빌드 → 지오코딩(캐시로 대부분 스킵) → 제주 특화 추가 를 올바른 순서로 실행
- Cloud Run Job에서 Cloud Scheduler로 월 1회 자동 실행 (asia-northeast3 = 한국 IP라 해수욕장도 됨)
- 로컬(해외 IP)에서는 해수욕장 수집이 0건 날 수 있음 — 그 단계만 실패해도 나머지는 진행

실행: python data_pipeline/refresh_all.py
전략 상세: docs/data-management.md
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# (스크립트, 실패해도 계속할지) — 순서 중요!
# ⚠️ build_db가 테이블을 재생성하므로, 카테고리별 수집기(4~)는 반드시 build_db 뒤에!
STEPS = [
    ("collect_restroom.py", True),    # 1. 전국 화장실 원본
    ("collect_camping.py", True),     #    야영장 원본
    ("collect_beach.py", True),       #    해수욕장 (한국 IP 필요, 실패해도 계속)
    ("build_db.py", False),           # 2. SQLite 재빌드 (+지오코딩 캐시 복원) — 실패 시 중단
    ("geocode_restroom.py", True),    # 3. 신규 주소만 지오코딩
    ("collect_dunchi.py", True),      # 4. 둔치주차장
    ("collect_jeju_ev.py", True),     #    제주 전기차
    ("collect_jeju_safety.py", True), #    제주 CCTV·클린하우스
    ("collect_jeju_pharmacy.py", True),  # 제주 심야약국
    ("collect_parking.py", True),     #    전국주차장표준데이터 (추천 후보군 핵심)
    ("collect_festival_std.py", True),   # 전국문화축제표준 (지도 메인 축제 레이어)
    ("collect_tourinfo.py", True),       # 전국관광안내소표준
    ("collect_festival.py --naive", True),  # 제주 행사'소식'→festival_news (GPT 연결 후 --naive 제거, #12)
]
# ※ RAG 보조데이터(시티투어·테마파크·한옥 CSV)는 prepare_rag_data.py 수동 실행 (분기 1회면 충분)


def run(script: str) -> bool:
    print(f"\n{'='*50}\n▶ {script}\n{'='*50}")
    name, *args = script.split()
    r = subprocess.run([PY, str(ROOT / "data_pipeline" / name), *args])
    return r.returncode == 0


def main():
    results = {}
    for script, keep_going in STEPS:
        ok = run(script)
        results[script] = ok
        if not ok and not keep_going:
            print(f"\n❌ {script} 실패 — 필수 단계라 중단합니다.")
            break

    print(f"\n{'='*50}\n=== 갱신 요약 ===")
    for s, ok in results.items():
        print(f"  {'✅' if ok else '⚠️'} {s}")
    print("\n※ 실서비스 갱신 후: facilities.db → GCS 업로드 (docs/data-management.md)")


if __name__ == "__main__":
    main()
