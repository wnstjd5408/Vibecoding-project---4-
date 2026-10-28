from fastapi import FastAPI

from app.common import install_common_layer

app = FastAPI(title="Vibecoding project 4 API")
# 엔드포인트 라우터는 prefix="/api"로 만들어 여기에 붙인다. 공통 헤더·Origin 검사는 /api 아래에만 적용한다.
install_common_layer(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
