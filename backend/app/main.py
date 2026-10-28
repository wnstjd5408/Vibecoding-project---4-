from fastapi import FastAPI

from app.common import install_common_layer

app = FastAPI(title="Vibecoding project 4 API")
# 엔드포인트 라우터는 prefix="/api"로 만들어 여기에 붙인다. 공통 헤더·Origin 검사는 /api 아래에만 적용한다.
install_common_layer(app)


@app.get("/health", include_in_schema=False)
@app.get("/api/health", summary="API server liveness")
def health() -> dict[str, str]:
    """API 서버 응답만 확인한다. DB·Auth·AI 연결을 검사하지 않는다."""
    return {"status": "ok"}
