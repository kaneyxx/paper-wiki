# paper-wiki release process

> What it takes to ship a tagged release of paper-wiki. The flow is
> small enough to keep in one file but strict enough that the
> v0.3.x install-UX line never regresses (SPEC §8.6 TWO-restart
> contract) and v0.4.x's digest-quality contract (decision **D-S**)
> stays intact.

## 1. Pre-flight (before opening the release PR)

Run on the release-candidate branch:

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest -q
claude plugin validate .
```

All five gates must pass. The `pytest` step includes
`tests/integration/test_d_s_regression_baseline.py`, which is the
**synthetic** half of the D-S contract — see §3 below for the manual
half.

## 2. Version bump (three places, kept in sync)

Bump in lockstep:

| Path                         | Field                  |
|------------------------------|------------------------|
| `src/paperwiki/__init__.py`  | `__version__ = "X.Y.Z"`|
| `pyproject.toml`             | `version = "X.Y.Z"`    |
| `.claude-plugin/plugin.json` | `"version": "X.Y.Z"`   |

A regression guard in `tests/test_smoke.py` asserts the manifest +
pyproject versions match `paperwiki.__version__`, so a partial bump
fails CI rather than at tag time.

## 3. D-S live-feed verification (manual, caller's responsibility)

Per **decision D-S** (consensus plan §3 Round 3), digest output-quality
regression is the only show-stopper for a release. The synthetic
test in `tests/integration/test_d_s_regression_baseline.py` locks in
fixture-level invariants; this manual step exercises the live arXiv
feed against a real recipe.

```bash
# 1. Build a personal `daily-arxiv` recipe with real vault paths +
#    a small max_results so the run finishes in <60s.
cp recipes/daily-arxiv.yaml /tmp/d-s-baseline.yaml
sed -i '' 's|<EDIT_ME_BEFORE_USE>|/tmp/d-s-vault|g' /tmp/d-s-baseline.yaml

# 2. Run on the v0.3.44 baseline (a clean checkout of the previous tag).
git -C /tmp/paperwiki-baseline checkout v0.3.44
/tmp/paperwiki-baseline/.venv/bin/python -m paperwiki.runners.digest /tmp/d-s-baseline.yaml \
    --target-date 2026-05-01

# 3. Run on the v0.4.0 candidate with the dedup ledger CLEARED so
#    silent dedup drops don't confound the comparison (D-S excludes
#    them explicitly).
rm -rf /tmp/d-s-vault/.paperwiki/dedup-ledger.jsonl
.venv/bin/python -m paperwiki.runners.digest /tmp/d-s-baseline.yaml \
    --target-date 2026-05-01

# 4. Compare:
#    - source.arxiv.fetched   — v0.4.0 should be >= v0.3.44
#    - filter.recency.dropped — same ratio (give or take 1-2 papers)
#    - filter.relevance.dropped — same ratio
#    - top-K paper ids — same overlap >= 80% (allow tail churn)
```

**Pass criteria**:

* Source coverage equal or better.
* Filter pass-rate within 5% of v0.3.44 (recency window + topic
  keyword set are unchanged, so a wide drift signals a regression).
* Top-K ranking overlap **≥ 80%** with v0.3.44 in the top 10. Set
  intersection by canonical id; ranking order can churn within the
  set without flagging.

If any criterion fails, do **not** push the tag. File a regression
issue, fix on the release branch, and re-run §1 + §3 from the top.
Migration loss, Obsidian indexing changes, and performance cliffs
are patchable rather than rollback-class — they get a follow-up
release per **D-S**.

### Re-run with the dedup ledger active

After the cleared-ledger pass goes green, re-run the same recipe
**without** clearing the ledger:

```bash
# Already populated by the prior run.
.venv/bin/python -m paperwiki.runners.digest /tmp/d-s-baseline.yaml
```

Verify:

* The digest emits zero recommendations on the second run (silent
  drop default per **D-F**).
* `paperwiki dedup-list --vault /tmp/d-s-vault` is empty (no
  dismissals, only `surfaced` rows).
* `paperwiki status --vault /tmp/d-s-vault` shows two clean ledger
  entries.

## 4. CHANGELOG

Add a new `## [X.Y.Z] - YYYY-MM-DD` block above the previous release
entry. Sections in order: a 2-3 sentence summary, **Phase X** /
**Added** / **Changed** / **Fixed** as appropriate, then the
ratified decision list (D-A through D-S for v0.4.x), then the
verification gate output. Keep wording in past tense.

## 5. Open the release PR

```bash
gh pr create \
    --base main \
    --title "Release vX.Y.Z" \
    --body "<short summary + link to CHANGELOG>"
```

The PR description should reference each phase and the D-S
verification record (paste counters from §3 step 4).

## 6. Tag and push

After the PR is merged into `main`:

```bash
git checkout main
git pull --ff-only
git tag -s vX.Y.Z -m "paper-wiki vX.Y.Z"
git push origin vX.Y.Z
```

The `-s` flag signs the tag with your GPG key; the marketplace
clone (used by `paperwiki update`) reads the tag verbatim.

## 7. Post-release smoke

After tagging:

```bash
# In a fresh terminal (not the one that just tagged), inside Claude Code:
/plugin install paper-wiki@paper-wiki
# Restart, then:
paperwiki status
paperwiki doctor
paperwiki digest <your-real-recipe.yaml>
```

`status` should show the new version. `doctor` should report all
sections green. `digest` should produce a digest file with the new
v0.4.x Properties block + Obsidian callouts (where the recipe enables
them) + a `<vault>/.paperwiki/run-status.jsonl` row.

## See also

* [`tasks/plan.md`](../tasks/plan.md) — full v0.4.x plan with
  decisions D-A through D-S and the per-task acceptance criteria.
* [`SPEC.md`](../SPEC.md) §8 — install-UX contract that v0.3.44
  ratified and v0.4.x preserves.
* [`tests/integration/test_d_s_regression_baseline.py`](../tests/integration/test_d_s_regression_baseline.py) —
  the synthetic half of the D-S contract.
