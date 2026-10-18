"""compose.yaml and compose.test.yaml follow BUILD.md §16 (T-47)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ONE_SHOT = {"migrate", "seed", "langfuse-db"}
# distroless images without a shell or a healthcheck subcommand (DECISIONS: observability profile)
NO_SHELL = {"otel-collector", "jaeger"}
BUILT_HERE = re.compile(r"^compliance-rag/")


def _compose(name: str) -> dict[str, Any]:
    return dict(yaml.safe_load((ROOT / name).read_text(encoding="utf-8")))


def _host_ports(service: dict[str, Any]) -> list[tuple[str, int]]:
    out = []
    for spec in service.get("ports", []):
        parts = str(spec).split(":")
        assert len(parts) == 3, f"bind every port to an address: {spec}"
        out.append((parts[0], int(parts[1])))
    return out


def test_ports_in_range_and_healthchecks() -> None:
    services = _compose("compose.yaml")["services"]
    seen: set[int] = set()
    for name, svc in services.items():
        for address, port in _host_ports(svc):
            assert address == "127.0.0.1", f"{name}: published on {address}"
            assert 8600 <= port <= 8699, f"{name}: host port {port} outside 8600-8699"
            assert port not in seen, f"{name}: port {port} used twice"
            seen.add(port)
        if name not in ONE_SHOT | NO_SHELL:
            # images built here declare HEALTHCHECK in their Dockerfile
            built = "build" in svc or bool(BUILT_HERE.match(str(svc.get("image", ""))))
            assert built or "healthcheck" in svc, f"{name}: no healthcheck"
        for dep, cond in (
            (svc.get("depends_on") or {}).items() if isinstance(svc.get("depends_on"), dict) else []
        ):
            expected = "service_completed_successfully" if dep in ONE_SHOT else "service_healthy"
            assert cond["condition"] == expected, f"{name} -> {dep}: {cond}"
    assert {8600, 8610, 8612, 8620, 8630, 8640, 8641, 8642, 8643} <= seen


def test_spec_ports_profiles_and_heap() -> None:
    services = _compose("compose.yaml")["services"]
    ports = {name: [p for _, p in _host_ports(svc)] for name, svc in services.items()}
    assert ports["web"] == [8600] and ports["api"] == [8610] and ports["dev-oidc"] == [8612]
    assert ports["worker"] == [8611] and ports["postgres"] == [8620] and ports["redis"] == [8630]
    assert (
        ports["opensearch"] == [8640] and sorted(ports["minio"]) == [8641, 8642] and ports["qdrant"] == [8643]
    )
    assert sorted(ports["otel-collector"]) == [8680, 8681] and ports["grafana"] == [8690]
    assert ports["prometheus"] == [8691] and ports["jaeger"] == [8692] and ports["langfuse"] == [8693]
    profiles = {p for svc in services.values() for p in svc.get("profiles", [])}
    assert profiles == {"qdrant", "observability", "langfuse", "live"}
    heap = str(services["opensearch"]["environment"])
    assert "-Xms512m -Xmx512m" in heap
    live = services["api-live"]
    assert live["environment"]["DEMO_MODE"] == "live" and live["profiles"] == ["live"]


def test_images_are_pinned() -> None:
    for compose in ("compose.yaml", "compose.test.yaml"):
        for name, svc in _compose(compose)["services"].items():
            image = svc.get("image")
            if image is None or BUILT_HERE.match(image):
                continue
            tag = image.split("@")[0].rsplit(":", 1)
            assert len(tag) == 2 and tag[1] != "latest" and re.search(r"\d", tag[1]), f"{name}: {image}"
    for dockerfile in (ROOT / "docker").glob("*.Dockerfile"):
        for line in dockerfile.read_text().splitlines():
            if line.startswith("FROM "):
                ref = line.split()[1]
                assert "@sha256:" in ref, f"{dockerfile.name}: base image not pinned by digest: {ref}"


def test_test_compose_runs_the_suites_against_the_stack_services() -> None:
    tests = _compose("compose.test.yaml")["services"]["tests"]
    env = tests["environment"]
    for key in ("DATABASE", "REDIS", "OPENSEARCH", "S3_ENDPOINT", "QDRANT"):
        assert f"CRAG_TEST_{key}_URL" in env, key
    command = " ".join(tests["command"]) if isinstance(tests["command"], list) else tests["command"]
    for suite in ("tests/unit", "tests/harness", "tests/integration", "tests/contract"):
        assert suite in command, suite
    assert set(tests["depends_on"]) >= {"postgres", "redis", "opensearch", "minio", "qdrant"}


def test_builds_use_the_host_network_only_when_asked() -> None:
    # `network: host` needs the network.host entitlement under buildx bake (GitHub runners refuse it); it is
    # needed only to reach a build proxy on the host, so `make` sets BUILD_NETWORK=host when HTTPS_PROXY is set
    for name in ("compose.yaml", "compose.test.yaml"):
        for service, svc in _compose(name)["services"].items():
            if "build" in svc:
                assert svc["build"]["network"] == "${BUILD_NETWORK:-default}", f"{name}: {service}"
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "export BUILD_NETWORK ?= $(if $(HTTPS_PROXY),host,default)" in makefile


def test_the_worker_healthcheck_does_not_import_the_worker() -> None:
    # `arq --check` imports the whole worker to read one Redis key: ~4 s of CPU every 10 s on the API's host
    test = _compose("compose.yaml")["services"]["worker"]["healthcheck"]["test"]
    assert test == ["CMD", "python", "/app/scripts/worker_healthcheck.py"]
