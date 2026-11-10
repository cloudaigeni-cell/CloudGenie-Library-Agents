# Agent Architecture: Anika Learning Deployment

![3D architecture overview](designs/agent-mcp-architecture-3d.png)

Illustrative single-host architecture. Connectors represent requests and returned
evidence, not permission to write to the snapshot. All LLM agents use the hosted
model API; MCP processes run locally on Anika. The existing Mermaid diagram below
is the editable logical reference.

This extends the v1 deterministic engine; it does not rename Python workers into
LLM agents. The manager and each specialist are independent Agents SDK agent
definitions, each with its own instructions and nested run context. The manager
decides tool calls using the configured model. Agents-as-tools keep ownership of
the final response with the manager. Work is divided by duty on one Ubuntu host,
not distributed across machines. Concurrency is decided by the SDK/model.

```mermaid
flowchart TD
    U[Human operator on Anika] --> S[Deterministic scan: explicitly selected exports]
    S --> E[Catalog, hashes, extracted text, duplicate and topic evidence]
    E --> F[Private frozen review snapshot]
    U --> C[Explicit model disclosure consent]
    C --> M[LLM manager: OpenAI Agents SDK]
    M --> Y[One real LLM subagent per year]
    M --> D[Global duplicate reviewer]
    M --> P[Global photo evidence reviewer]
    M --> T[Global document reviewer]
    M --> B[Global consolidation reviewer]
    Y --> MY[Year-scoped MCP subprocesses]
    D --> MG[Global read-only MCP subprocesses]
    P --> MG
    T --> MG
    B --> MG
    MY --> F
    MG --> F
    M --> R[Review report and local lifecycle events]
    R --> H[Human validation]
    H -. separate explicit CLI approvals .-> Q[Quarantine and optional purge workflow]
```

## Responsibilities and authority

| Component | Responsibility | Enforced boundary |
| --- | --- | --- |
| Deterministic coordinator | Parse and hash all selected files; global comparisons | No source writes during scan |
| Year subagent | Categorize one year and identify coverage gaps | Separate server filters inventory and evidence to that year |
| Duplicate reviewer | Inspect cross-year matching evidence | Read-only global snapshot; cannot authorize deletion |
| Photo reviewer | Explain pixel/perceptual evidence and metadata risks | No original pixels supplied; no claims of visual inspection |
| Document reviewer | Check supported formats and extraction status | Extracted text only after operator opt-in |
| Consolidation reviewer | Propose reading packs and identify unresolved evidence | No document editing or replacement authority |
| Manager | Delegate and assemble final report | Only specialist tools, no shell/filesystem/cleanup tools |
| MCP server | Serve bounded pages and enforce scope/disclosure | Fixed in-memory snapshot; no arbitrary path argument |
| Human CLI cleanup | Separate review, quarantine, restore and purge | Existing hash validation and explicit approval plans |

## MCP contract

![3D walkthrough of a year-scoped MCP inventory request](designs/mcp-tool-call-3d.png)

Read the tool-call illustration as: manager delegates, specialist requests a tool,
MCP enforces scope, evidence returns, specialist produces findings, manager combines
them, and the human reviews. The bottom findings document represents the specialist's
output. This is a conceptual sequence, not proof that live inference succeeded.

`audit_overview()` returns year scope, file count and limitations.
`list_inventory(offset, limit)` returns bounded metadata with extraction status.
`list_evidence(section, offset, limit)` serves approved evidence sections.
`read_document(file_id, offset, limit)` serves extracted units only with text
disclosure enabled. IDs outside the server scope are rejected. File paths cannot
be requested. Pages are limited to 50 items; document units to 4000 characters,
with explicit truncation flags. Follow `next_offset`; page counts do not prove
the model actually reviewed every result.

Cross-year groups are omitted from year-scoped tools, not partly represented.
Global reviewers receive complete groups. All agents use the same frozen input
snapshot. Prompts are defense in depth; tool authority is enforced in Python.
Source content is untrusted and may contain prompt injection. There is no
arbitrary execution tool for injected text to exploit.

## Model and observability boundary

SDK `Agent.as_tool()` runs real nested model loops. Every subagent connects to a
real MCP server subprocess using `MCPServerStdio`. The server itself is not an
LLM and cannot delegate. The deterministic scanner is not an LLM either.

Shared hooks log starts, tool names, finishes and usage. The global model-call
budget applies to nested runs; turn limits and timeout provide additional bounds.
A successful SDK return is not enough for claimed complete delegation: missing
specialist completions mark the run incomplete. Factual completeness still needs
human review. Provider retries and model billing are outside a dollar-budget gate.

No model or credentialed request is involved in `--probe`. It demonstrates MCP
transport, not intelligent delegation. Only a successful credentialed review
demonstrates the full agent loop.

## Deliberate limits and next stages

This release does not autonomously merge source documents, delete photos, connect
to a full live Google Photos library, use image vision, implement a multi-machine
queue, or provide resumable LLM conversations. Deterministic reading packs already
exist; the LLM reviewer proposes improvements but cannot declare them replacements.
The original v1 PDF remains the scanner guide. This document is the agent-layer
architecture supplement and includes the diagram source directly.
