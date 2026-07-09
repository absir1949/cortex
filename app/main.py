"""听风 FastAPI 入口

生命周期：
  startup:
    - 确保目录存在
    - 跑迁移（v1 & 之后的版本号迁移）
    - 启动 TaskRunner（清理幽灵 RUNNING 任务）
    - 启动 APScheduler

  shutdown:
    - 停 APScheduler
    - 停 TaskRunner

托管静态文件：
  /api/*   → REST API
  /*       → 前端静态文件（React SPA，fallback 到 index.html）
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.settings import settings
from app.db.migrations import run_migrations
from app.api import groups as groups_api
from app.api import sources as sources_api
from app.api import research as research_api
from app.api import tasks as tasks_api
from app.api import reports as reports_api
from app.api import config as config_api
from app.api import signals as signals_api
from app.api import creators as creators_api
from app.api import contents as contents_api
from app.api import platforms as platforms_api
from app.api import ask as ask_api
from app.api import auth as auth_api
from app.auth import get_current_user, require_admin
from app.tasks import get_runner
from app.tasks.handlers import ingest_handler, research_handler, analyze_handler  # noqa: F401 注册 handlers
from app.scheduler import get_scheduler


logger = logging.getLogger("cortex")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("听风 starting...")
    settings.ensure_dirs()

    # 数据库迁移（v1 等）
    try:
        applied = run_migrations(verbose=False)
        if applied:
            logger.info(f"migrations applied: {applied}")
    except Exception as e:
        logger.exception(f"migration failed: {e}")
        raise

    # 任务执行器（每次 lifespan 创建新实例，避免测试复用 shutdown 后的 executor）
    from app.tasks import set_runner
    from app.tasks.runner import TaskRunner
    runner = TaskRunner()
    set_runner(runner)
    ghosts = runner.startup()
    if ghosts:
        logger.warning(f"reset {ghosts} ghost running tasks to failed")

    # 调度器
    scheduler = get_scheduler()
    scheduler.start()
    logger.info(f"scheduler started with jobs: {[j['name'] for j in scheduler.list_jobs()]}")

    yield

    logger.info("听风 shutting down...")
    scheduler.shutdown(wait=False)
    runner.shutdown(wait=False)
    set_runner(None)


def create_app() -> FastAPI:
    app = FastAPI(
        title="听风",
        description="你的行业听风者（cortex）",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS（前端 dev 用 5180，生产同源不需要）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5180", "http://127.0.0.1:5180",  # dev（热重载）
            "http://localhost:5173", "http://127.0.0.1:5173",  # 兼容老端口
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST 路由：默认锁死，公开只留 auth/health/静态资源。
    user_deps = [Depends(get_current_user)]
    admin_deps = [Depends(require_admin)]
    app.include_router(auth_api.router)
    app.include_router(auth_api.me_router, dependencies=user_deps)
    app.include_router(groups_api.router, dependencies=user_deps)
    app.include_router(sources_api.router, dependencies=user_deps)
    app.include_router(research_api.router, dependencies=user_deps)
    app.include_router(tasks_api.router, dependencies=user_deps)
    app.include_router(reports_api.router, dependencies=user_deps)
    app.include_router(config_api.router, dependencies=admin_deps)
    app.include_router(signals_api.router, dependencies=user_deps)
    app.include_router(creators_api.router, dependencies=user_deps)
    app.include_router(contents_api.router, dependencies=user_deps)
    app.include_router(platforms_api.router, dependencies=user_deps)
    app.include_router(ask_api.router, dependencies=user_deps)

    # 调度器管理（热重载 job 定义）
    @app.post("/api/scheduler/reload", dependencies=admin_deps)
    def reload_scheduler():
        get_scheduler().reload()
        return {"ok": True, "jobs": get_scheduler().list_jobs()}

    @app.get("/api/scheduler/jobs", dependencies=admin_deps)
    def list_jobs():
        return get_scheduler().list_jobs()

    # 健康检查
    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # 静态文件（前端构建产物）- 仅当存在时挂载
    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            # API 已被上面的路由接管；这里只处理前端路由
            if full_path.startswith("api/"):
                return JSONResponse({"error": "not found"}, status_code=404)
            # 静态资源请求
            candidate = static_dir / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # SPA fallback
            index = static_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return JSONResponse({"message": "前端未构建。访问 /docs 查看 API。"}, status_code=200)
    else:
        @app.get("/")
        def root():
            return {"message": "听风 API. 访问 /docs 查看端点。"}

    return app


app = create_app()
