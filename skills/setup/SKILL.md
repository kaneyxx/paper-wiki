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
recipe; use AskUserQuestion to ask the user whether to reconfigure first.

## Process

### Step 0 — Verify the venv

Run `bash ${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh` and confirm
`${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists afterwards.

### Step 1 — Run diagnostics

Invoke
`${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.diagnostics`
and parse the JSON. Note the `mcp_servers` field for the paperclip step later.

### Step 2 — Detect existing config (Branch 1)

Check whether `~/.config/paper-wiki/recipes/daily.yaml` already exists.

**If it exists**, use AskUserQuestion to prompt:

**Question:** "Paper-wiki is already configured. What would you like to do?"

**Options:**
1. Keep current config — verify health (venv + diagnostics), then exit
2. Reconfigure from scratch — re-run the 5-question wizard, overwrite daily.yaml
3. Edit one piece — pick a single field to change
4. Cancel

If user chooses "Keep current config": run Step 0 + Step 1, confirm
health, show a summary, and exit.

If user chooses "Reconfigure from scratch": proceed to Q1 wizard below.

If user chooses "Edit one piece": go to Branch 2 (drill-down) below.

If user chooses "Cancel": exit immediately without changes.

---

### Branch 2 — Edit one piece (drill-down)

Use AskUserQuestion to prompt:

**Question:** "Which piece would you like to edit?"

**Options:**
1. Vault path
2. Topics
3. Semantic Scholar API key
4. auto_ingest_top
5. Cancel

For each option, collect only that field via the relevant wizard step
(Q1 through Q4 below), then merge it into the existing `daily.yaml`
and write. Show a confirmation summary after saving.

If user chooses "Cancel": return to the previous menu (re-run Branch 1).

---

### Q1 — Vault path (Branch 3)

Run the following to collect candidates:
```
ls -d ~/Documents/*Vault* ~/Documents/*Wiki* ~/Documents/Paper-Wiki ~/Obsidian* 2>/dev/null
```

Use AskUserQuestion to prompt:

**Question:** "Where should paper-wiki put your Obsidian vault?"

**Options:** (pre-populate with any paths found above, one per option)
- e.g. `~/Documents/Paper-Wiki`
- e.g. `~/Obsidian/Research`
- Other (specify path) — if chosen, follow up with a plain free-form
  question: "Enter the vault path:" and accept the user's typed response.

Validate the path. If it does not exist, offer to `mkdir -p` it.
Save as the vault path used throughout the recipe.

---

### Q2 — Topics (Branch 4)

Use AskUserQuestion to prompt (repeat until "Done" is selected, accumulating
all picks — each round re-prompt with the same question, keeping track of
what has been chosen so far):

**Question:** "Which research areas interest you? (Pick all that apply — I will re-prompt until you choose Done.)"

**Options:**
1. Vision-Language (VLM, foundation models)
2. Pathology / Medical Imaging
3. Multi-modality (cross-modal, VQA)
4. Diffusion Models (DDPM, latent diffusion)
5. Agents (tool use, reasoning)
6. NLP / Language Models
7. Computer Vision (general)
8. Reinforcement Learning
9. Other (specify keywords) — if chosen, follow up with a free-form
   question: "Enter keywords (comma-separated):" and add them as a
   custom topic.
10. Done — proceed to next question

Keep calling AskUserQuestion until the user picks "Done", accumulating
all selected topics. For each built-in topic, use the corresponding
preset `keywords` and `categories` (default `cs.CV, cs.LG`). Custom
keywords from option 9 are added as a topic named `custom` with
`categories: cs.CV, cs.LG` as the default.

---

### Q3 — Semantic Scholar API key (Branch 5)

Use AskUserQuestion to prompt:

**Question:** "Add a Semantic Scholar API key now? (Bumps rate limit ~1 req/s → 100 req/s — strongly recommended.)"

**Options:**
1. Yes — I'll paste the key (follow up with a free-form question to
   capture it, then write to `~/.config/paper-wiki/secrets.env` as
   `export PAPERWIKI_S2_API_KEY="<key>"` with `chmod 600`)
2. Skip for now — use without a key (rate-limited)
3. Help me get one — show URL `https://www.semanticscholar.org/product/api#api-key-form`
   then re-prompt this same question

If "Yes": validate the key looks like a ~40 alphanumeric-char string
before writing. Flag malformed keys before writing — the wrong string
causes silent 401s later.

---

### Q4 — auto-ingest depth (Branch 6)

Use AskUserQuestion to prompt:

**Question:** "Auto-chain wiki-ingest for top-N papers after every digest?"

**Options:**
1. None (0) — just produce the digest, no auto-ingest
2. Top 3 (recommended for daily use)
3. Top 5
4. Custom (enter integer 1-20) — follow up with a free-form question
   to capture the integer

Save the result as `auto_ingest_top: <n>` in the recipe. Default 3.

---

### Q5 — paperclip / biomedical (Branch 7)

Consult the `mcp_servers` field from diagnostics (Step 1).

Use AskUserQuestion to prompt:

**Question:** "Do you have paperclip CLI installed for biomedical search?"

**Options:**
1. Yes — `paperclip` is on $PATH and logged in (write
   `recipes/biomedical-weekly.yaml`)
2. Skip — not interested in biomedical sources
3. How do I install it — show `docs/paperclip-setup.md` and the
   registration command verbatim:
   `claude mcp add --transport http paperclip https://paperclip.gxl.ai/mcp`
   Do NOT auto-run this command — emit it for the user to run themselves.
   Auth is sensitive. Then re-prompt this question.

If `paperclip` is already listed in `mcp_servers`: confirm cheerfully
that paperclip MCP is registered, mention
`recipes/biomedical-weekly.yaml` as a starting point, and skip to
the confirmation step.

---

### Final confirmation (Branch 8)

Display a summary of all values collected:
- Vault path
- Topics selected
- S2 API key: provided / skipped
- auto_ingest_top value
- paperclip: registered / not registered / declined

Then use AskUserQuestion to prompt:

**Question:** "Ready to save? Here's what I'll write to ~/.config/paper-wiki/:"

**Options:**
1. Save and exit
2. Edit a value before saving (returns to Branch 2 — Edit one piece)
3. Cancel without saving

If "Save and exit": write the recipe (Step 9) and show the next-step
suggestion.

---

### Step 9 — Write the recipe

Build the YAML from the wizard answers:
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

### Step 10 — Confirm + next step

Show the user a summary:
- Recipe saved to `~/.config/paper-wiki/recipes/daily.yaml`
- Secrets saved to `~/.config/paper-wiki/secrets.env` (if any)
- paperclip MCP: registered / not registered / declined

Then suggest: `/paperwiki:digest` to run their first morning digest.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The user just wants to skip setup." | Without a personal recipe, every digest invocation falls back to bundled templates that point at the wrong vault. Walk through the five questions; it's three minutes. |
| "I'll trust whatever the user says about their vault path." | Validate that the path exists and is writable; an invalid path silently breaks every later SKILL. Offer to `mkdir -p` it explicitly. |
| "The venv is probably fine; no need to verify." | Stale or partial venvs are the most common silent failure. Run `ensure-env.sh` and confirm the `.installed` stamp every time. |
| "The user gave me their API key — I'll just inline it in the recipe." | NEVER inline secrets in YAML files that may be shared. Always go through `api_key_env: PAPERWIKI_S2_API_KEY` + `~/.config/paper-wiki/secrets.env`. The recipe stays shareable; the secret stays secret. |
| "All five questions in one message — fast for the user!" | Walk through them one at a time using AskUserQuestion. Multi-question prompts get half-answered and the SKILL ends up guessing the rest. |
| "Default everything; the user can edit later." | The user came to setup specifically to make decisions. Defaults are a fallback for "I don't know", not a substitute for asking. |
| "I can just render the options as markdown bullet points." | Use AskUserQuestion for every choice point. Rendering options as prose leaves Claude to guess which one the user picked; AskUserQuestion gives a structured selection UI. |

## Red Flags

- `ensure-env.sh` exits non-zero or the `.installed` stamp is missing —
  the venv is broken; rerun the script and inspect the output before
  asking any wizard question.
- The diagnostics runner emits empty or non-JSON output — Python
  imports are broken; nuke `.venv` and rerun `ensure-env.sh`.
- The user already has `~/.config/paper-wiki/recipes/daily.yaml` and
  you are about to overwrite without asking — always confirm via
  AskUserQuestion (Branch 1).
- The user mentions Chinese vault paths or templates — surface the
  locales option but keep English as the default for the wizard.
- The user asks you to "register paperclip for me" or similar —
  explain that paperclip auth is sensitive; emit the command for them
  to run themselves. Never auto-run `claude mcp add` without explicit
  consent. Do not auto-run the registration command — show it verbatim
  without auto-running it.
- `mcp_servers` already lists `paperclip` but the user wants it
  registered again — surface the existing registration and ask whether
  to remove it first; do not stack duplicates.
- The user pastes an S2 API key that doesn't match the expected
  shape (~40 alphanumeric chars) — flag it before writing, the wrong
  string will cause silent 401s later.
- Claude renders choice options as markdown prose instead of calling
  AskUserQuestion — this breaks the structured selection UI and is the
  primary failure mode this SKILL is designed to prevent.

## Verification

- `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists.
- `~/.config/paper-wiki/recipes/daily.yaml` exists and parses as a
  valid `RecipeSchema` (the digest runner will reject it loudly if
  not).
- `~/.config/paper-wiki/secrets.env` exists with mode `600` when the
  user provided an API key.
- Claude called AskUserQuestion for each branch (Branches 1–8) rather
  than rendering options as markdown bullet points. If options appear
  only as prose with no AskUserQuestion call, the SKILL has failed its
  primary UX contract.
- `/paperwiki:digest` (the next-step command) loads the recipe
  successfully — confirm by running it once at the end of setup if
  the user is willing.
