# Anika: Ubuntu Deployment and Learning Guide

## Deployment layout

- Host: Anika, local WSL2 Ubuntu; user: techforge.
- Application: `/home/techforge/CloudGenie-Library-Agents`.
- Python environment: `.venv` inside the application directory.
- Generated data: `demo-data/` and `runs/`, excluded from Git.
- Transport: local MCP subprocesses over stdio. No listening TCP port, SSH,
  firewall changes, inbound cloud connection, or fixed WSL IP is required.
- The observed `172.25.217.17` address is not embedded in configuration.
- No boot service or scheduled scan is installed. A review starts its own MCP
  subprocesses and closes them when it exits. Closing WSL interrupts active work.

## Install or reproduce

Use Python 3.11+ (Anika has Python 3.12). These commands create a fresh checkout;
skip cloning and venv creation on the already deployed host.

```bash
cd /home/techforge
git clone https://github.com/cloudaigeni-cell/CloudGenie-Library-Agents.git
cd CloudGenie-Library-Agents
git switch codex/cloudaigeni-mcp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[analysis,agents]'
python -m unittest discover -s tests -v
```

The optional Agents SDK and MCP versions are pinned in `pyproject.toml`.
The base deterministic scanner retains Python 3.10 compatibility; the agent
extra requires Python 3.11+. This is not an OS-isolated security sandbox.

## Lesson 1: Build deterministic evidence

The deployed demo is already generated. For a fresh installation only:

```bash
python examples/create_demo.py demo-data
python -m library_agents scan --source demo-data --output runs/demo
```

The demo refuses to overwrite an existing directory. PDF and PPT examples also
need the optional `reportlab` package; without it the demo contains seven files.
Read `runs/demo/REPORT.md`, `inventory.csv`, and `duplicates.json` first.
The scan workers are ordinary Python, not LLM agents. They produce independently
inspectable hashes, extracted text and evidence before any model sees data.

## Lesson 2: Talk to a real MCP server without an LLM

```bash
cd /home/techforge/CloudGenie-Library-Agents
source .venv/bin/activate
library-agent-review --run runs/demo --probe
```

This launches a real server process, discovers its four tools, calls
`audit_overview`, and closes the connection. `llm_called: false` is intentional.
No key or model is needed. The transport test also checks that text access is
denied by default and that a nonexistent deletion tool fails.

## Lesson 3: Run the manager and real subagents

Configure your own authorized API model. Do not paste keys into chat, source
code, screenshots, shell history, or Git. Enter the key silently in this terminal:

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
export OPENAI_API_KEY
read -rp 'Model ID available to your API account: ' OPENAI_MODEL
export OPENAI_MODEL
library-agent-review --run runs/demo --allow-model-disclosure --max-model-calls 40
unset OPENAI_API_KEY
```

Model access and any applicable usage charges belong to your API account. The
application does not infer entitlement from a ChatGPT login. The model identifier
is deliberately not hard-coded. Start with synthetic data, not your full library.

`--allow-model-disclosure` allows metadata such as filenames, years, hashes,
categories, duplicate IDs and topic keywords to be sent to OpenAI. Full paths and
cloud URLs are not exposed by these MCP tools. Metadata can still be sensitive.
`--include-text` additionally permits bounded extracted document content to be
sent. It does not send original photo pixels or perform LLM vision review.

SDK cloud tracing is disabled. Local events contain agent names, tool names,
model-call numbers and token counts, not raw prompts or tool results. The local
snapshot, manifest and final report can contain personal data: keep `runs/`
private. Output directories on Linux are created with mode 0700. Model requests
still leave the host; disabling tracing does not make hosted inference local.

Watch the console for `agent_start`, `model_start`, `tool_start`, and `model_end`.
Open the unique `runs/agent-.../` directory afterwards:

- `agent-manifest.json`: specialist instructions, year scopes, model and limits.
- `agent-events.jsonl`: actual SDK lifecycle events, not simulated narration.
- `AGENT-REVIEW.md`: model-generated review, requiring human validation.
- `status.json`: complete, incomplete (missing specialists), or failed.
- `snapshot/`: frozen input evidence used by all specialist MCP processes.

The shared limit counts model calls across manager and specialists. Each specialist
has a 12-turn limit, manager 40 turns, and the entire run a 30-minute timeout.
Retries within a provider request can still incur usage. These are operational
limits, not a dollar cap. Configure a provider-side spending limit as well.

## Lesson 4: Audit real exports, only after reviewing privacy

Run the deterministic scan against extracted Takeout files first. Every source
is explicitly chosen with `--source`; the review only receives the resulting
catalog. Do not rescan or edit that run while a review is starting. Use a new
output directory for each review; existing output directories are rejected.

Google Photos access is not added by MCP. This deployment works on exported
files, not a live complete Google Photos account. Deleting an exported copy does
not reclaim Google Photos quota. Cloud deletion is not implemented.

## Failure handling and operations

- Missing key/model: set terminal environment variables; do not commit secrets.
- Authentication, quota or unavailable-model errors: check your API account.
- Budget or timeout: inspect failed status and events; retry with a new output
  directory after deciding whether more model usage is appropriate.
- Incomplete report: inspect coverage; do not treat it as a complete inventory.
- Extraction errors: deterministic inventory remains the authority for gaps.
- Stop: Ctrl+C; source files remain untouched. Partial output is retained.
- Upgrade: inspect Git changes, then `git pull --ff-only` and reinstall extras.
- Cleanup: never delegated to an LLM. Existing human-approved CLI workflows
  remain separate; this MCP server cannot invoke them.

## Validation boundary

Local tests exercise real stdio MCP, scopes, pagination and denial behavior.
They do not prove model quality or replace a credentialed live run. No live
LLM review was performed during initial deployment because no key was configured.

References: [OpenAI SDK MCP integration](https://developers.openai.com/api/docs/guides/agents/integrations-observability),
[manager and agents-as-tools](https://developers.openai.com/api/docs/guides/agents/orchestration),
[MCP Python server](https://py.sdk.modelcontextprotocol.io/run/).
