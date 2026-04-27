---
name: setup
description: Interactive first-run wizard. Verifies paper-wiki's Python environment, walks the user through five questions to build their personal recipe (vault path, topics, S2 API key, auto-ingest preference), writes the config files, and surfaces optional MCP servers. Use when the user invokes /paper-wiki:setup, when no personal recipe exists yet at ~/.config/paper-wiki/recipes/, or when downstream paperwiki SKILLs report missing config.
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

After setup, the user runs `/paper-wiki:digest` and everything Just
Works — Claude finds the personal recipe, sources the secrets, runs
the pipeline, and (if `auto_ingest_top > 0`) folds top papers into
concept articles.

## When to Use

- The user types `/paper-wiki:setup`.
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

**AskUserQuestion call:**
- question: "Paper-wiki is already configured. What would you like to do?"
- header: "Setup mode"
- multiSelect: false
- options:
  1. label: "Keep current config"
     description: "Verify health (venv + diagnostics), then exit without changes."
  2. label: "Reconfigure from scratch"
     description: "Re-run the 5-question wizard and overwrite daily.yaml."
  3. label: "Edit one piece"
     description: "Drill into a specific field — vault path, topics, key, or auto-ingest."

Note: Claude Code automatically appends a Cancel option — do NOT add one manually.

If user chooses "Keep current config": run Step 0 + Step 1, confirm
health, show a summary, and exit.

If user chooses "Reconfigure from scratch": proceed to Q1 wizard below.

If user chooses "Edit one piece": go to Branch 2 (drill-down) below.

If user chooses Cancel (auto-provided): exit immediately without changes.

---

### Branch 2 — Edit one piece (drill-down)

Use AskUserQuestion to prompt:

**AskUserQuestion call:**
- question: "Which piece would you like to edit?"
- header: "Edit field"
- multiSelect: false
- options:
  1. label: "Vault path"
     description: "Change the Obsidian vault directory location."
  2. label: "Topics"
     description: "Add or remove research areas used for filtering."
  3. label: "S2 API key"
     description: "Rotate or add your Semantic Scholar API key."
  4. label: "Auto-ingest"
     description: "Change how many top papers are auto-ingested after each digest."

Note: Claude Code automatically appends a Cancel option — do NOT add one manually.

For each option, collect only that field via the relevant wizard step
(Q1 through Q4 below), then merge it into the existing `daily.yaml`
and write. Show a confirmation summary after saving.

If user chooses Cancel (auto-provided): return to the previous menu (re-run Branch 1).

---

### Q1 — Vault path (Branch 3)

Run the following to collect candidates:
```
ls -d ~/Documents/*Vault* ~/Documents/*Wiki* ~/Documents/Paper-Wiki ~/Obsidian* 2>/dev/null
```

Use AskUserQuestion to prompt:

**AskUserQuestion call:**
- question: "Where should paper-wiki put your Obsidian vault?"
- header: "Vault"
- multiSelect: false
- options: (pre-populate with up to 3 paths found above; always include the creation option)
  - label: "~/Documents/Paper-Wiki" (if that path exists)
    description: "Existing folder detected at this location."
  - label: "~/Documents/Obsidian-Vault" (if that path exists)
    description: "Existing folder detected at this location."
  - label: "Create new"
    description: "Create a fresh vault at ~/Documents/Paper-Wiki/ with mkdir -p."

Cap at 4 total options. Claude Code automatically appends an Other option for
custom paths — do NOT add a manual "Other" option. If the user selects the
auto-provided Other, follow up with a free-form question to capture the path.

Validate the path. If it does not exist, offer to `mkdir -p` it.
Save as the vault path used throughout the recipe.

---

### Q2 — Topics (Branch 4)

Use AskUserQuestion to prompt using `multiSelect: true`. The user can
select multiple themes in a single interaction — there is no need to
re-prompt until "Done". Claude Code automatically appends an Other option
for custom keywords — do NOT add a manual "Other" option and do NOT add
a "Done" option; multiSelect handles submission.

**AskUserQuestion call:**
- question: "Which research areas interest you? Select all that apply."
- header: "Topics"
- multiSelect: true
- options:
  1. label: "Vision & Multimodal"
     description: "Vision-language, VLM, multimodal, VQA, diffusion models."
  2. label: "Biomedical & Pathology"
     description: "Pathology, WSI, foundation models for medicine, clinical AI."
  3. label: "Agents & Reasoning"
     description: "Tool use, planning, agents, reasoning, RL."
  4. label: "NLP & Language"
     description: "LLMs, language models, instruction tuning, alignment."

If the user selects the auto-provided Other, treat the free-form text as
custom keywords and create a 5th topic entry in the recipe.

#### Theme → keywords mapping

When writing the recipe YAML, expand each selected theme using this table:

```
Vision & Multimodal:
  keywords: [vision-language, vision language model, VLM, foundation model,
             multimodal, multi-modal, cross-modal, VQA, visual question answering,
             diffusion model, denoising diffusion, latent diffusion]
  categories: [cs.CV, cs.LG, cs.MM]

Biomedical & Pathology:
  keywords: [pathology, histopathology, WSI, whole-slide image, whole slide image,
             digital pathology, medical imaging, clinical AI, foundation model]
  categories: [cs.CV, eess.IV, q-bio.QM]

Agents & Reasoning:
  keywords: [agent, tool use, reasoning, planning, ReAct, chain-of-thought,
             reinforcement learning, RLHF]
  categories: [cs.AI, cs.MA, cs.LG]

NLP & Language:
  keywords: [language model, LLM, large language model, instruction tuning,
             alignment, RLHF, prompt engineering]
  categories: [cs.CL, cs.LG]
```

If the user provided custom keywords via auto-Other, append them as a 5th
topic with `categories: [cs.CV, cs.LG]` as the catch-all default.

---

### Q3 — Semantic Scholar API key (Branch 5)

Use AskUserQuestion to prompt:

**AskUserQuestion call:**
- question: "Add a Semantic Scholar API key now? (Bumps rate limit ~1 req/s → 100 req/s — strongly recommended.)"
- header: "S2 API key"
- multiSelect: false
- options:
  1. label: "Paste key now"
     description: "Key saved to ~/.config/paper-wiki/secrets.env with mode 600."
  2. label: "Skip — no key"
     description: "Rate limited to ~1 req/s; OK for casual use."
  3. label: "Show how to get one"
     description: "Open API key signup URL: https://www.semanticscholar.org/product/api#api-key-form"

If "Paste key now": follow up with a free-form question to capture it.
Validate the key looks like a ~40 alphanumeric-char string before writing.
Write to `~/.config/paper-wiki/secrets.env` as
`export PAPERWIKI_S2_API_KEY="<key>"` with `chmod 600`.
Flag malformed keys before writing — the wrong string causes silent 401s later.

If "Show how to get one": display the URL, then re-prompt this same question.

---

### Q4 — auto-ingest depth (Branch 6)

Use AskUserQuestion to prompt:

**AskUserQuestion call:**
- question: "Auto-chain wiki-ingest for top-N papers after every digest?"
- header: "Auto-ingest"
- multiSelect: false
- options:
  1. label: "None"
     description: "Digest only — no auto wiki-ingest."
  2. label: "Top 3 (recommended)"
     description: "Ingest top 3 papers after each digest."
  3. label: "Top 5"
     description: "Ingest top 5 — heavier compute."

Claude Code automatically appends an Other option for custom values — do NOT
add a manual "Custom" option. If the user selects auto-Other, follow up with
a free-form question to capture an integer (1-20).

Save the result as `auto_ingest_top: <n>` in the recipe. Default 3.

---

### Q5 — paperclip / biomedical (Branch 7)

Consult the `mcp_servers` field from diagnostics (Step 1).

Use AskUserQuestion to prompt:

**AskUserQuestion call:**
- question: "Do you have paperclip CLI installed for biomedical search?"
- header: "Paperclip"
- multiSelect: false
- options:
  1. label: "Yes — installed"
     description: "paperclip is on PATH and logged in; biomedical recipe will be written."
  2. label: "Skip"
     description: "No biomedical sources; skip this step."
  3. label: "How to install"
     description: "Show docs/paperclip-setup.md and the registration command verbatim."

If "How to install": show `docs/paperclip-setup.md` and the
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

**AskUserQuestion call:**
- question: "Ready to save? Here's what I'll write to ~/.config/paper-wiki/:"
- header: "Save?"
- multiSelect: false
- options:
  1. label: "Save and exit"
     description: "Write the recipe and secrets files, then show next steps."
  2. label: "Edit before save"
     description: "Go back to Branch 2 to change a specific field."

Note: Claude Code automatically appends a Cancel option — do NOT add one manually.

If "Save and exit": write the recipe (Step 9) and show the next-step
suggestion.

If "Edit before save": return to Branch 2 — Edit one piece.

If Cancel (auto-provided): exit without saving.

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

Then suggest: `/paper-wiki:digest` to run their first morning digest.

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
| "I should add an 'Other' or 'Cancel' option myself." | Claude Code injects these automatically. Manually adding them violates the AskUserQuestion schema and causes UI bugs like duplicate options or split tabs. |
| "Topics need 10 fine-grained options." | AskUserQuestion hard-caps at 4 options; exceeding this causes Claude Code to auto-split them into multiple tabs (the 'Topics (1)/(2)' bug). Use 4 themed buckets with multiSelect: true instead. |
| "I'll skip the header field — the question text is clear enough." | The header field is REQUIRED. Omitting it causes Claude Code to truncate the question text into a garbage label like 'Custom kw'. Always provide header (max 12 chars). |

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
- An AskUserQuestion call is missing a `header` field — Claude Code
  truncates the question text into a garbage chip label. Every call
  must specify `header` (≤ 12 chars).
- An AskUserQuestion call has more than 4 options — Claude Code
  auto-splits them across tabs (producing "Topics (1)" / "Topics (2)"
  style bugs). Hard cap is 4 options; use multiSelect: true + themed
  buckets for multi-pick scenarios.
- A manual "Other", "Cancel", or "Done" option was added to an
  AskUserQuestion call — Claude Code injects these automatically.
  Adding them manually produces duplicates and schema violations.

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
- Every AskUserQuestion call includes a `header` field (≤ 12 chars).
- No AskUserQuestion call has more than 4 options.
- No AskUserQuestion call includes a manually-added "Other", "Cancel",
  or "Done" option — Claude Code provides these automatically.
- The topics question uses `multiSelect: true` so users can select
  multiple themes in a single interaction without re-prompting.
- `/paper-wiki:digest` (the next-step command) loads the recipe
  successfully — confirm by running it once at the end of setup if
  the user is willing.
