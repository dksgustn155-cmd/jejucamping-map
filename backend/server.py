"""배포용 단일 진입점 — main(프론트·시설) + chat(추천·GPT·피드백)을 한 서버로 합침.

이유: 프론트가 chat.py 를 부를 때 별도 도메인(localhost:8011)을 쓰면 배포 시 CORS·URL 문제가 생김.
     한 서버로 합쳐 같은 도메인(/agent 하위)에서 서빙 → 프론트 AGENT_BASE="/agent".

로컬·운영 동일하게 실행:  uvicorn backend.server:app --port 8000
Cloud Run 도 이 진입점을 사용 (PORT 환경변수는 uvicorn --port $PORT 로 전달).
"""
import os

# SSL_CERT_FILE 이 없거나 깨진 경로면 certifi 로 교정 (일부 로컬 PC 대비 · 운영엔 무해)
if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:  # noqa: BLE001
        pass

from backend.main import app          # noqa: E402 — 프론트 정적·/config.js·/api/facilities·/api/recommend
from backend import chat              # noqa: E402,F401 — 아래에서 /agent 하위로 마운트

# chat.py 의 FastAPI 앱(추천·GPT·피드백·MCP)을 /agent 하위에 마운트.
# Starlette 가 마운트된 서브앱의 lifespan(=chat 의 MCP 세션매니저)을 함께 실행한다.
app.mount("/agent", chat.app)
