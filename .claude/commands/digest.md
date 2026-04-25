---
description: Build a paper-wiki digest from a recipe and write it to disk
---

Invoke the paper-wiki digest skill.

If the user named a recipe (e.g. "weekly", "daily", "sources-only"),
match it to `recipes/<name>.yaml` under the plugin root. Otherwise
default to `recipes/daily-arxiv.yaml`. If the user passes a date,
forward it as `--target-date YYYY-MM-DD`.

After the digest runs, summarize the top 3 recommendations and tell
the user where the digest file was written.
