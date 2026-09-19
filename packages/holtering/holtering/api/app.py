"""Сборка Litestar: контейнер зависимостей, ошибки в problem+json, собранный фронтенд."""

from http import HTTPStatus

from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.litestar import setup_dishka
from litestar import Litestar, get
from litestar.exceptions import HTTPException
from litestar.plugins.problem_details import (
    ProblemDetailsConfig,
    ProblemDetailsException,
    ProblemDetailsPlugin,
)
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


def _problem(exc: HTTPException) -> ProblemDetailsException:
    """RFC 9457: `title` — общее имя класса ошибки, `detail` — что именно случилось."""
    return ProblemDetailsException(
        status_code=exc.status_code,
        title=HTTPStatus(exc.status_code).phrase,
        detail=exc.detail,
        extra=exc.extra,
        headers=exc.headers,
    )


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
        plugins=[
            ProblemDetailsPlugin(
                ProblemDetailsConfig(exception_to_problem_detail_map={HTTPException: _problem})
            )
        ],
        on_shutdown=[container.close],
        logging_config=None,
    )
    setup_dishka(container, app)
    return app
