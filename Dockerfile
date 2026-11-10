FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY library_agents ./library_agents
RUN pip install --no-cache-dir '.[analysis]'
RUN useradd --uid 10001 --create-home auditor
USER auditor
ENTRYPOINT ["python", "-m", "library_agents"]
