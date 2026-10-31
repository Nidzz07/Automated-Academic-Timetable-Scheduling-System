"""S16b (ROADMAP D55): the production app serves the API under /api and the built frontend
at /, index.html for every other path. A stand-in dist in a scratch directory, chosen
through CHRONOS_FRONTEND_DIST; the API is backend.app.main's, on the scratch database."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main, prod
from backend.app.main import create_app
from backend.app.store import REPO
from backend.tests.conftest import AUTH, bearer

INDEX = "<!doctype html><title>Chronos</title>"


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("dist")
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def client(dist: Path, database_url: str) -> Iterator[TestClient]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CHRONOS_FRONTEND_DIST", str(dist))
        app = prod.create_app(create_app(database_url=database_url, auth=AUTH))
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/index.html", "/timetable/se-a", "/assets/missing.js"])
def test_index_for_the_root_and_unknown_paths(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")


def test_built_files_are_served(client: TestClient) -> None:
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_api_under_api(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/instances").status_code == 401
    listed = client.get("/api/instances", headers=bearer("student"))
    assert listed.status_code == 200
    assert {"id": "even-2025-26"} in listed.json()


def test_unknown_api_path_is_the_api_404_not_the_page(client: TestClient) -> None:
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("path", ["/api/docs", "/api/redoc", "/api/openapi.json"])
def test_production_serves_no_api_docs(dist: Path, path: str) -> None:
    # S14r: prod's own API (no lifespan needed to route); local development keeps the docs
    assert TestClient(prod.create_app(dist=dist)).get(path).status_code == 404
    assert TestClient(main.app).get(path.removeprefix("/api")).status_code == 200


def test_image_installs_the_pinned_versions() -> None:
    # backend/requirements.prod.txt (S14r) repeats requirements.txt's pins, never others
    def pins(path: Path) -> dict[str, str]:
        lines = (raw.split("#")[0].strip() for raw in path.read_text("utf-8").splitlines())
        pairs = (line.split("==") for line in lines if line)
        return {name.split("[")[0].lower(): version for name, version in pairs}

    prod_pins = pins(REPO / "backend" / "requirements.prod.txt")
    assert prod_pins.items() <= pins(REPO / "requirements.txt").items()
    assert "pytest" not in prod_pins and "networkx" not in prod_pins


def test_start_fails_without_a_built_frontend(tmp_path: Path, database_url: str) -> None:
    app = prod.create_app(create_app(database_url=database_url, auth=AUTH), dist=tmp_path)
    with pytest.raises(RuntimeError, match="no built frontend"), TestClient(app):
        pass
