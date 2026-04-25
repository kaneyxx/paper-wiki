# paper-wiki

> A personal research wiki builder for Claude Code. Pipeline-driven paper
> ingestion with a plugin architecture.

`paper-wiki` turns the firehose of academic publishing into a curated,
queryable, knowledge-accumulating wiki. SKILLs let you fetch papers from
arXiv and Semantic Scholar, filter and score them against your research
interests, and persist durable notes into a Markdown vault — all from
inside Claude Code.

## Status

Pre-v0.1. The plugin protocol is **experimental** and may change before
the first stable release.

## Install

In Claude Code:

```text
/plugin marketplace add kaneyxx/paper-wiki
/plugin install paper-wiki@paper-wiki
```

The plugin self-installs its Python environment on first session — no
manual setup required. If `uv` is on your `PATH` it will be used; the
plugin falls back to stdlib `venv` + `pip` otherwise.

## Quick start

1. `/paperwiki:setup` — verify your environment and configure your vault.
2. `/paperwiki:digest` — generate your first research digest.
3. `/paperwiki:wiki-query` — search across your accumulated notes.

## How it works

paper-wiki composes a four-stage async pipeline:

```text
Source → Filter → Scorer → Reporter
```

Each stage is a pluggable `Protocol`. Built-in plugins ship with the
project; external plugins are discovered automatically via Python entry
points.

A "recipe" YAML file declares which plugins to use and how to configure
them, so you can describe a complete research workflow without writing
code.

## Architecture and contributing

- See [SPEC.md](SPEC.md) for the full operating contract.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contributor guidelines (TBD).
- The Python implementation lives under `src/paperwiki/`. End users do
  not import this directly — SKILLs invoke it through bundled runners.

## License

[GPL-3.0](LICENSE)
