---
paths: ["src/compliance_rag/llm/**", "src/compliance_rag/graph/**", "src/compliance_rag/embed/**", "src/compliance_rag/rerank/**", "prompts/**", "scripts/eval_live.py"]
---
# LLM integration rules

- Load the `claude-api` skill before writing code that calls Claude; it beats memory.
- All model calls go through `src/compliance_rag/llm/gateway.py`: provider selection, timeouts, retries, token and cost accounting, tracing and PII redaction. No other module imports `anthropic` or `openai` (import-linter enforces it).
- Model IDs come from settings (`CRAG_MODEL_*`), never from logic. Defaults: `claude-opus-5-5` for generation, `claude-haiku-5-5` for condense and judge. Bedrock uses `anthropic.`-prefixed IDs. Never append date suffixes.
- Structured output via `output_config.format` JSON schema or `messages.parse()`; never force tool use (`tool_choice` any/tool returns 400 on Opus 5.5); no assistant prefill.
- Adaptive thinking with explicit `output_config.effort` per route; never send `budget_tokens` or disabled thinking to Opus 5.5.
- Check `stop_reason` first: handle `refusal` (abstain), `max_tokens` (error), tool loops. Retry only 408, 409, 429, 5xx and connection errors with backoff and jitter.
- Stream long outputs; stable prompt prefixes first, cache-marked.
- Prompts live in `prompts/<name>.v<N>.md`; every call records prompt version, model, tokens, cost, latency and outcome.
- Every route has a deterministic fake (`FakeLLM`) used by tests and `DEMO_MODE=offline`; cassettes override the fake. Provider adapters are tested against recorded responses only.
- Validate every model output against its schema before it is persisted or acted on. The model has no tools and proposes no side effects.
