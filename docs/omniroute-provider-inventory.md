# OmniRoute 3.8.51 — VERIFIED PROVIDER INVENTORY (2026-10-08)
Source: installed package / DB / CLI health / source constants — NOT README claims only.

TOTAL OMNIROUTE PROVIDERS (from source constants):
- NOAUTH: 5 (devin-cli-agentic, duckduckgo-web, cloudflare-playground, veoaifree-web, codex-app-server)
- OAUTH: 11 (ghe-copilot, xai-oauth, grok-cli, amazon-q, gitlab-duo, zed-hosted, kimi-coding, devin-desktop, devin-cli, codebuddy-cn, muse-code)
- APIKEY: defined via registry (not in separate file); includes openrouter, together, groq, gemini-api, openai, anthropic, deepseek-api, etc.
- WEB_COOKIE: 27 (chatgpt-web, gemini-web, grok-web, claude-web, deepseek-web, kimi-web, doubao-web, zenmux-free, etc.)
- LOCAL: 6 (ollama-local, lm-studio, mlx-gemma, mlx-qwen, llama-cpp, docker-model-runner)
- SEARCH: 15
- RETIRED (triggers enforce unavailable): qwen-web (v3.8.51), chatgpt-web/cgpt-web, felo-web/felo, msdesigner

TOTAL MODELS (catalog): 358 (from CLI health / radar feed); zero in DB model_context_overrides / provider_nodes.
FREE VERIFIED (with active connection): 0 — configuredCount=0.
FREE AUTH_REQUIRED: all catalog entries that have free tier but need key (unknown exact count from static catalog).
FREE LIVE: 0 (no connections active).
PAID: unknown from static catalog alone — not counted as verified without connection.
UNKNOWN: 358 - 0 = 358 (catalog exists but unverified against runtime).
DEPRECATED/RETIRED: qwen-web, chatgpt-web, felo-web, msdesigner (trigger-enforced unavailable).

TOP 20 VERIFIED FREE MODELS: NONE verified live (configuredCount=0). Conservative candidates only if configured:
1. (none live)
...
BEST CODING: not verified — requires configured upstream.
BEST REASONING: not verified.
BEST FAST: not verified.
BEST AGENT/TOOLS: not verified.
BEST LONG-CONTEXT: not verified.

AUTH / FALLBACK: if provider connection missing -> AUTH_REQUIRED (not excluded permanently). If connection exists but fails -> UNAVAILABLE (retryable per FREE-AUTO health). If tier unknown -> UNKNOWN (not counted free).
