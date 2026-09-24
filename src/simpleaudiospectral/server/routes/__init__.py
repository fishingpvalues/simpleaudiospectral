"""Route table. Each route is a function (handler, query) -> None that sends
one response; exceptions become status codes in Handler.errors_as_responses."""

from . import analysis, library, media, session, views
from .media import static

GET_ROUTES = {
    "/api/health": session.health,
    "/api/ls": library.ls,
    "/api/roots": library.roots,
    "/api/search": library.search,
    "/api/info": analysis.info,
    "/api/stats": analysis.stats,
    "/api/scan": analysis.scan,
    "/api/gonio": views.gonio,
    "/api/stft": views.stft,
    "/api/wave": views.wave,
    "/api/audio": media.audio,
    "/api/spectrogram": media.spectrogram,
}

POST_ROUTES = {
    "/api/login": session.login,
    "/api/logout": session.logout,
}

__all__ = ["GET_ROUTES", "POST_ROUTES", "static"]
