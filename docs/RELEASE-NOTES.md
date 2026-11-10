# Version 1 Release Notes

Date: 10 November 2026.

This first implementation provides local agent orchestration, year and format specialists, global exact duplicate evidence, image comparison candidates, extracted-text topic packs, source provenance, resumable caching and reviewed local cleanup with restoration and a separate purge gate.

Default scans do not modify source data or use network access. Optional Ollama summaries require an explicit model argument. Optional OCR processes image files only and needs a separately installed Tesseract executable.

This release does not include Google authentication, Photos cloud deletion, private endpoint scraping, a web dashboard, an MCP server, distributed remote execution, scanned-PDF OCR, semantic video comparison or lossless replacement of original Office documents. See the guide for deployment, review steps and known limits.

The included sample run is synthetic. No real photographs, documents or account data were processed by the framework during development.
