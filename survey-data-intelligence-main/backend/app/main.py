import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.batches import router as batches_router
from app.api.health import router as health_router
from app.db import init_db
from app.modules.ingestion.router import router as ingest_router
from app.modules.ingestion.ocr.router import router as ocr_router
from app.modules.sirl.router import router as sirl_router
from app.modules.validation.router import router as validation_router
from app.modules.validation.statistics.router import router as statistics_router
from app.modules.validation.ml.router import router as ml_router
from app.modules.validation.fusion.router import router as fusion_router
from app.modules.validation.explanation.router import router as explanation_router
from app.modules.ai.router import router as ai_router
from app.modules.auth.deps import get_current_user
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import esigma_router, router as dashboard_router
from app.modules.investigations.router import router as investigations_router
from app.modules.pipeline.router import router as pipeline_router
from app.modules.validation.intelligence.router import router as intelligence_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from app.db import SessionLocal
    from app.modules.pipeline.jobs import start_workers
    from app.modules.pipeline.recovery import recover_abandoned_runs

    try:
        start_workers()
    except Exception:
        logging.getLogger("pipeline.jobs").exception("PIPELINE_WORKER_START_FAILED")
        raise
    db = SessionLocal()
    try:
        recover_abandoned_runs(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Intelligent Survey Data Validation Platform",
    lifespan=lifespan,
)



app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^https?://(localhost|127\.0\.0\.1|192\.168\.0\.100)(:\d+)?$"
        r"|^https://data-validator-chi\.vercel\.app$"
        r"|^https://data-validator-git-main-bhavatharanis-projects\.vercel\.app$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
protected = [Depends(get_current_user)]

app.include_router(health_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(esigma_router, prefix="/api")
app.include_router(ingest_router, prefix="/api", dependencies=protected)
app.include_router(ocr_router, prefix="/api", dependencies=protected)
app.include_router(batches_router, prefix="/api", dependencies=protected)
app.include_router(sirl_router, prefix="/api", dependencies=protected)
app.include_router(validation_router, prefix="/api", dependencies=protected)
app.include_router(statistics_router, prefix="/api", dependencies=protected)
app.include_router(ml_router, prefix="/api", dependencies=protected)
app.include_router(fusion_router, prefix="/api", dependencies=protected)
app.include_router(explanation_router, prefix="/api", dependencies=protected)
app.include_router(dashboard_router, prefix="/api", dependencies=protected)
app.include_router(intelligence_router, prefix="/api", dependencies=protected)
app.include_router(pipeline_router, prefix="/api", dependencies=protected)
app.include_router(investigations_router, prefix="/api", dependencies=protected)
