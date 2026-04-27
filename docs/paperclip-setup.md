# Paperclip MCP setup

[paperclip](https://gxl.ai/blog/paperclip) is a search engine over 8M+
biomedical papers (bioRxiv, medRxiv, PubMed Central). paper-wiki can
optionally use it as a source plugin and as an MCP-driven search
surface in the `bio-search` SKILL.

> **Stance**: paperclip is **optional**. paper-wiki works without it;
> all paperclip-using SKILLs short-circuit gracefully when the MCP
> server is not registered. Adopt it only if biomedical literature is
> in your reading mix.

---

## 1. Install the paperclip CLI

paperclip ships a CLI that handles auth, caching, and search. Install
it once:

```bash
curl -fsSL https://paperclip.gxl.ai/install.sh | bash
```

The installer drops `paperclip` into `~/.local/bin` (or wherever your
shell PATH points). Verify:

```bash
paperclip --version
```

If `paperclip` isn't on your PATH after install, add the install
location to your shell rc (`~/.bashrc` / `~/.zshrc`).

## 2. Authenticate

```bash
paperclip login
```

This opens a browser to authenticate against your paperclip account.
Free-tier and paid-tier capabilities are documented at
<https://gxl.ai/blog/paperclip>; paper-wiki does not duplicate that
matrix here because the upstream maintainer owns it.

> **Privacy note**: `paperclip login` stores credentials under your
> user's config dir. paper-wiki never reads or transmits these
> credentials; we shell out to the CLI when invoked, and the CLI
> handles auth itself.

## 3. Register the MCP server with Claude Code

Once the CLI is installed and you're logged in, register paperclip's
MCP endpoint with Claude Code:

```bash
claude mcp add --transport http paperclip https://paperclip.gxl.ai/mcp
```

Verify the registration:

```bash
claude mcp list
```

You should see `paperclip` listed. paper-wiki's `/paper-wiki:setup`
SKILL surfaces this state via `paperwiki.runners.diagnostics`.

> **Important**: paper-wiki's setup SKILL **never auto-runs**
> `claude mcp add`. Auth is sensitive and the user may be on a
> metered plan. The SKILL hands you the command; you opt in.

## 4. Try a SKILL that uses paperclip

After registration, the bio-search SKILL becomes available
(Phase 7.3, shipping in v0.3.0):

```
/paper-wiki:bio-search "vision-language foundation models in pathology"
```

If paperclip MCP is missing, the SKILL surfaces an actionable error
pointing back at this document — paper-wiki itself stays usable.

## 5. Removing the registration

```bash
claude mcp remove paperclip
```

paper-wiki notices the absence on the next `/paper-wiki:setup` run and
silently drops paperclip from its capabilities list. No state cleanup
needed on paper-wiki's side.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `claude mcp list` doesn't show paperclip | Registration missing | Re-run the `claude mcp add` line in §3. |
| `paperclip login` fails repeatedly | Stale auth cache | `paperclip logout`, then retry. |
| `bio-search` SKILL warns "MCP not registered" | Registration removed or never ran | Re-register per §3. |
| paper-wiki recipe references `paperclip` source but errors | The `PaperclipSource` plugin needs the *CLI*, not the MCP | Verify §1; the CLI is what the source plugin shells out to. |

## See also

- Upstream paperclip docs: <https://paperclip.gxl.ai>
- Phase 7 plan: [`tasks/plan.md`](../tasks/plan.md) §4
- `bio-search` SKILL (when shipped): `skills/bio-search/SKILL.md`
