---
name: setup
description: Interactive first-run wizard. Verifies paper-wiki's Python environment, walks the user through five questions to build their personal recipe (vault path, topics, S2 API key, auto-ingest preference), writes the config files, and surfaces optional MCP servers. Use when the user invokes /paperwiki:setup, when no personal recipe exists yet at ~/.config/paper-wiki/recipes/, or when downstream paperwiki SKILLs report missing config.
---

# paper-wiki Setup

## Overview

Setup is the first-run onboarding wizard. It does three things:

1. **Verifies the environment** (Python venv, diagnostics output,
   optional MCP servers like paperclip).
2. **Asks five questions** to build the user's personal `daily.yaml`
   recipe — vault path, topics, S2 API key, auto-ingest depth, and
   whether to add paperclip.
3. **Writes two files** that downstream SKILLs read:
   - `~/.config/paper-wiki/recipes/daily.yaml` — the personal recipe
   - `~/.config/paper-wiki/secrets.env` — the API keys (chmod 600)

After setup, the user runs `/paperwiki:digest` and everything Just
Works — Claude finds the personal recipe, sources the secrets, runs
the pipeline, and (if `auto_ingest_top > 0`) folds top papers into
concept articles.

## When to Use

- The user types `/paperwiki:setup`.
- A paper-wiki SKILL fails because no personal recipe exists at
  `~/.config/paper-wiki/recipes/daily.yaml`.
- The user reports broken Python imports inside
  `${CLAUDE_PLUGIN_ROOT}/.venv`.
- The user asks "how do I configure paper-wiki?", "where do I point
  it at my vault?", "do I need an API key?", "walk me through setup".

**Do not use** when the user is asking about a specific recipe, a
specific paper, or pipeline output — those route to other SKILLs.
**Do not re-run** unprompted on a vault that already has a personal
recipe; ask the user whether to reconfigure first.

## Process

1. **Verify the venv.** Run
   `bash ${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh` and confirm
   `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists afterwards.
2. **Run diagnostics.** Invoke
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.diagnostics`
   and parse the JSON. Note the `mcp_servers` field for step 8.
3. **Detect existing config.** If
   `~/.config/paper-wiki/recipes/daily.yaml` already exists, ask the
   user whether to **reconfigure** (overwrite), **edit by hand**
   (open the file in their editor), or **skip** (just confirm health
   and exit). Default to skip when in doubt.
4. **Wizard Q1 — vault path.** Ask:
   > Where should paper-wiki write your daily digests, source notes,
   > and concept articles? (e.g. `~/Documents/Paper-Wiki`)

   Validate the path. If it doesn't exist, offer to `mkdir -p` it.
   Default suggestion: `~/Documents/Paper-Wiki`.
5. **Wizard Q2 — topics.** Offer five common research areas as
   pre-built topic blocks (vision-language, agents, pathology,
   multi-modality, diffusion-models) and let the user pick any
   subset, plus custom topics. For each, capture:
   - `name`: short slug
   - `keywords`: comma-separated phrases
   - `categories`: arXiv categories (default `cs.CV, cs.LG` if user
     doesn't know)

   Ask:
   > Which topics do you want in your daily digest? Pick from
   > common areas or describe your own:
   > - vision-language / VLM / multimodal foundation models
   > - agents / tool use / reasoning
   > - pathology / histopathology / WSI
   > - multi-modality / cross-modal
   > - diffusion-models / DDPM / latent diffusion
   > Or list custom keywords (comma-separated).
6. **Wizard Q3 — Semantic Scholar API key.** Ask:
   > Do you have a Semantic Scholar API key? It's free and bumps the
   > rate limit from ~1 req/s to 100 req/s.
   > 1. Yes — paste it now (saved to `~/.config/paper-wiki/secrets.env`,
   >    chmod 600, gitignored).
   > 2. No — I'll add a placeholder; you can paste later.
   > 3. Skip — run with arXiv only.

   If Yes: validate it looks like a 40-char hex string before saving;
   write to `~/.config/paper-wiki/secrets.env` as
   `export PAPERWIKI_S2_API_KEY="<key>"`; `chmod 600` the file.
7. **Wizard Q4 — auto-ingest depth.** Ask:
   > How many top papers should auto-fold into concept articles each
   > morning? (Each one is a Claude synthesis pass.)
   > - 0 = manual: I just write the digest; you run wiki-ingest yourself
   > - 1 = light: only the day's #1 paper auto-ingests
   > - 3 = recommended: top-3
   > - 5 = aggressive: top-5

   Default 3. Save as `auto_ingest_top: <n>` in the recipe.
8. **Wizard Q5 — paperclip / biomedical** *(only ask if the user
   mentions life sciences in step 5)*. Read the diagnostics
   `mcp_servers` field:
   - If `paperclip` is registered → confirm cheerfully, mention
     `recipes/biomedical-weekly.yaml` as a starting point.
   - If not registered → offer the registration command verbatim
     (`claude mcp add --transport http paperclip https://paperclip.gxl.ai/mcp`)
     plus a link to `docs/paperclip-setup.md`. **Do NOT auto-run**;
     auth is sensitive.
9. **Write the recipe.** Build the YAML from the wizard answers:
   ```yaml
   name: personal-daily
   sources:
     - {name: arxiv, config: {categories: [...], lookback_days: 3, max_results: 200}}
     - {name: semantic_scholar, config: {query: "<first topic keyword>",
        lookback_days: 7, limit: 50, api_key_env: PAPERWIKI_S2_API_KEY}}
   filters:
     - {name: recency, config: {max_days: 7}}
     - {name: relevance, config: {topics: [...]}}
     - {name: dedup, config: {vault_paths: ["<vault>/Daily", "<vault>/Sources",
        "<vault>/Wiki/sources", "<vault>/Wiki/concepts"]}}
   scorer: {name: composite, config: {topics: [...], weights: {...}}}
   reporters:
     - {name: markdown, config: {output_dir: "<vault>/.digest-archive"}}
     - {name: obsidian, config: {vault_path: "<vault>", daily_subdir: Daily,
        wiki_backend: true}}
   top_k: 10
   auto_ingest_top: <n>
   ```

   Use the `Write` tool to save it to
   `~/.config/paper-wiki/recipes/daily.yaml` (or to
   `$PAPERWIKI_CONFIG_DIR/recipes/daily.yaml` if the user has that env
   var set — power users pointing at e.g. `~/dotfiles/paper-wiki/` get
   that directory written instead). Create the dir first (`mkdir -p`).
10. **Confirm + next step.** Show the user a summary:
    - Recipe saved to `~/.config/paper-wiki/recipes/daily.yaml`
    - Secrets saved to `~/.config/paper-wiki/secrets.env` (if any)
    - paperclip MCP: registered / not registered / declined

    Then suggest: `/paperwiki:digest` to run their first morning
    digest.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The user just wants to skip setup." | Without a personal recipe, every digest invocation falls back to bundled templates that point at the wrong vault. Walk through the five questions; it's three minutes. |
| "I'll trust whatever the user says about their vault path." | Validate that the path exists and is writable; an invalid path silently breaks every later SKILL. Offer to `mkdir -p` it explicitly. |
| "The venv is probably fine; no need to verify." | Stale or partial venvs are the most common silent failure. Run `ensure-env.sh` and confirm the `.installed` stamp every time. |
| "The user gave me their API key — I'll just inline it in the recipe." | NEVER inline secrets in YAML files that may be shared. Always go through `api_key_env: PAPERWIKI_S2_API_KEY` + `~/.config/paper-wiki/secrets.env`. The recipe stays shareable; the secret stays secret. |
| "All five questions in one message — fast for the user!" | Walk through them one at a time. Multi-question prompts get half-answered and the SKILL ends up guessing the rest. |
| "Default everything; the user can edit later." | The user came to setup specifically to make decisions. Defaults are a fallback for "I don't know", not a substitute for asking. |

## Red Flags

- `ensure-env.sh` exits non-zero or the `.installed` stamp is missing —
  the venv is broken; rerun the script and inspect the output before
  asking any wizard question.
- The diagnostics runner emits empty or non-JSON output — Python
  imports are broken; nuke `.venv` and rerun `ensure-env.sh`.
- The user already has `~/.config/paper-wiki/recipes/daily.yaml` and
  you are about to overwrite without asking — always confirm.
- The user mentions Chinese vault paths or templates — surface the
  locales option but keep English as the default for the wizard.
- The user asks you to "register paperclip for me" or similar —
  explain that paperclip auth is sensitive; emit the command for them
  to run themselves. Never auto-run `claude mcp add` without explicit
  consent.
- `mcp_servers` already lists `paperclip` but the user wants it
  registered again — surface the existing registration and ask whether
  to remove it first; do not stack duplicates.
- The user pastes an S2 API key that doesn't match the expected
  shape (~40 alphanumeric chars) — flag it before writing, the wrong
  string will cause silent 401s later.

## Verification

- `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists.
- `~/.config/paper-wiki/recipes/daily.yaml` exists and parses as a
  valid `RecipeSchema` (the digest runner will reject it loudly if
  not).
- `~/.config/paper-wiki/secrets.env` exists with mode `600` when the
  user provided an API key.
- `/paperwiki:digest` (the next-step command) loads the recipe
  successfully — confirm by running it once at the end of setup if
  the user is willing.
