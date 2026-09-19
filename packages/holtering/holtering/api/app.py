"""Сборка Litestar: контейнер зависимостей, ошибки в problem+json, собранный фронтенд."""

from __future__ import annotations

from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.litestar import setup_dishka
from litestar import Litestar, get
from litestar.plugins.problem_details import ProblemDetailsConfig, ProblemDetailsPlugin
from litestar.response import File
from litestar.static_files import create_static_files_router
from litestar.types import ControllerRouterHandler

from holtering.analysis import State
from holtering.api.routes import api_router
from holtering.settings import Settings


class RecordProvider(Provider):
    """Одна запись на процесс: приложение однопользовательское и локальное."""

    scope = Scope.APP

    def __init__(self, settings: Settings, state: State) -> None:
        super().__init__()
        self._settings = settings
        self._state = state

    @provide
    def settings(self) -> Settings:
        return self._settings

    @provide
    def state(self) -> State:
        return self._state


def create_app(settings: Settings, state: State) -> Litestar:
    container = make_async_container(RecordProvider(settings, state))
    handlers: list[ControllerRouterHandler] = [api_router]
    static_dir = settings.api.static_dir
    if static_dir is not None and static_dir.exists():
        index_file = static_dir / "index.html"

        @get("/", include_in_schema=False, sync_to_thread=False)
        def index() -> File:
            return File(index_file, media_type="text/html", content_disposition_type="inline")

        handlers += [
            create_static_files_router("/assets", directories=[static_dir / "assets"]),
            index,
        ]
    app = Litestar(
        route_handlers=handlers,
        plugins=[ProblemDetailsPlugin(ProblemDetailsConfig(enable_for_all_http_exceptions=True))],
        on_shutdown=[container.close],
        logging_config=None,
    )
    setup_dishka(container, app)
    return app
