import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api.admin import router as admin_router
from api.health import router as health_router
from api.jivo_webhook import router as jivo_router
from database.db import create_db_and_tables
from products.remote_xml_importer import ProductRemoteXmlImporter
from products.remote_xml_scheduler import ProductsXmlAutoImportRunner
from settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    create_db_and_tables()
    settings = get_settings()
    auto_import_runner = None
    if settings.products_xml_auto_import_enabled:
        remote_importer = ProductRemoteXmlImporter.from_settings(settings)
        auto_import_runner = ProductsXmlAutoImportRunner(
            import_once=remote_importer.download_and_import,
            interval_seconds=settings.products_xml_auto_import_interval_seconds,
            run_on_startup=settings.products_xml_auto_import_run_on_startup,
        )
        await auto_import_runner.start()
        app.state.products_xml_auto_import_runner = auto_import_runner

    try:
        yield
    finally:
        if auto_import_runner is not None:
            await auto_import_runner.stop()


def create_application() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(admin_router)
    app.include_router(health_router)
    app.include_router(jivo_router)
    return app


app = create_application()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=False)
