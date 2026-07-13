# ----- Stage 1: Base -----
ARG PYTHON_VER=3.12
FROM docker.io/python:${PYTHON_VER}-slim AS base

ENV PYTHONUNBUFFERED=1
ENV PATH="${PATH}:/root/.local/bin"

RUN groupadd -r -g 1000 app && useradd --no-log-init -u 1000 --home-dir /opt/app -r -g app app

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y curl ca-certificates git && \
    curl -sSL https://astral.sh/uv/install.sh | sh - && \
    apt-get autoremove -y && \
    apt-get clean all && \
    rm -rf /var/lib/apt/lists/*

# ----- Stage 2: Application -----
FROM base

WORKDIR /app

# Copy workspace manifests first for layer caching: third-party dependencies
# only re-install when a manifest or the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY planner/pyproject.toml planner/
COPY orchestrator/pyproject.toml orchestrator/
COPY executor/pyproject.toml executor/
COPY validator/pyproject.toml validator/
COPY tools/ibnctl/pyproject.toml tools/ibnctl/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-workspace

# Copy the workspace packages and install them
COPY planner/ planner/
COPY orchestrator/ orchestrator/
COPY executor/ executor/
COPY validator/ validator/
COPY tools/ibnctl/ tools/ibnctl/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Planner policies ship next to the planner package, not inside the wheel;
# point the orchestrator at the copy baked into this image. Both /data paths
# are expected to be volume mounts in real deployments.
ENV IBN_POLICIES_DIR=/app/planner/policies
ENV IBN_PLANS_DIR=/data/plans
ENV IBN_SOT_REPO=/data/sot-repo

USER 1000

# Split ENTRYPOINT (the CLI) from CMD (subcommand + flags) so a Kubernetes
# container-args-only override swaps the subcommand or flags while keeping the
# entrypoint. Default: the reconcile watch loop, the one long-running service
# (docs/architecture/runtime-topology.md).
ENTRYPOINT ["ibn-orchestrate"]
CMD ["watch", "--interval", "15"]
