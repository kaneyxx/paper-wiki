#!/usr/bin/env python3
"""Deterministic builder for the synthetic 100-note fixture vault.

Per consensus plan iter-2 R10 + §"Plan body — 9.156a", this script produces
``tests/fixtures/synthetic_vault_100/`` with 40 papers + 30 concepts +
20 topics + 10 people, organised across 5 thematic research clusters
(vlm, llm-reasoning, robotics-rl, protein-structure, generative-models).
The seed (42) is fixed so re-running the builder produces byte-identical
output.

The fixture is consumed by:

* 9.157 (wiki_compile_graph) byte-equality tests
* 9.158 (wiki-lint --check-graph) scaling tests
* Scenario 3 (perf cliff) regression — soft 10s budget warning
* Scenario 5 (vault-layout rollback round-trip) end-to-end test

Run from the repo root:

    python tests/fixtures/build_synthetic_vault.py

The output directory is wiped and rebuilt on each run.
"""

from __future__ import annotations

import random
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make ``paperwiki`` importable when running this script standalone from
# the repo root (``src/`` is the package root).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperwiki.core.models import (  # noqa: E402
    Concept,
    Person,
    Topic,
)
from paperwiki.core.templates import (  # noqa: E402
    render_concept,
    render_person,
    render_topic,
)

SEED = 42  # locked per plan §9.156a acceptance.
# Fixed timestamp for the Obsidian Properties block (task 9.161). The
# fixture must stay byte-identical across rebuilds, so we hard-code this
# rather than using ``datetime.now()``.
FIXTURE_WHEN = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
FIXTURE_ROOT = Path(__file__).parent / "synthetic_vault_100"
PAPERS_PER_CLUSTER = 8
CONCEPTS_PER_CLUSTER = 6
TOPICS_PER_CLUSTER = 4
PEOPLE_PER_CLUSTER = 2

# Five thematic clusters, each contributing 20 notes (8+6+4+2). The
# concepts / topics / people are deliberately recognisable real-world
# names so the fixture reads as a believable researcher's vault rather
# than as random tokens. Names are public-domain research identifiers
# (papers' arxiv IDs, well-known concept names); no PII is introduced.
CLUSTERS: list[dict[str, list[str]]] = [
    {
        "slug": ["vlm"],
        "topics": [
            "vision-language-foundation-models",
            "multimodal-learning",
            "image-text-alignment",
            "zero-shot-classification",
        ],
        "concepts": [
            "clip",
            "vision-transformer",
            "contrastive-loss",
            "prompt-engineering",
            "image-encoder",
            "text-encoder",
        ],
        "people": ["alec-radford", "jong-wook-kim"],
    },
    {
        "slug": ["llm-reasoning"],
        "topics": [
            "chain-of-thought",
            "in-context-learning",
            "tool-use",
            "reasoning-evaluation",
        ],
        "concepts": [
            "cot-prompting",
            "instruction-tuning",
            "rlhf",
            "attention-mechanism",
            "decoder-only",
            "scaling-laws",
        ],
        "people": ["jason-wei", "denny-zhou"],
    },
    {
        "slug": ["robotics-rl"],
        "topics": [
            "imitation-learning",
            "sim-to-real",
            "manipulation",
            "vision-language-action",
        ],
        "concepts": [
            "behavior-cloning",
            "ppo",
            "dagger",
            "diffusion-policy",
            "action-chunking",
            "world-model",
        ],
        "people": ["sergey-levine", "chelsea-finn"],
    },
    {
        "slug": ["protein-structure"],
        "topics": [
            "protein-folding",
            "sequence-design",
            "structure-prediction",
            "function-prediction",
        ],
        "concepts": [
            "alphafold",
            "esm",
            "msa-attention",
            "equivariant-network",
            "contact-map",
            "structure-token",
        ],
        "people": ["john-jumper", "andriy-kryshtafovych"],
    },
    {
        "slug": ["generative-models"],
        "topics": [
            "diffusion-models",
            "autoregressive-image",
            "video-generation",
            "audio-generation",
        ],
        "concepts": [
            "ddpm",
            "classifier-free-guidance",
            "latent-diffusion",
            "score-matching",
            "vqvae",
            "flow-matching",
        ],
        "people": ["jonathan-ho", "prafulla-dhariwal"],
    },
]


def _arxiv_id(cluster_idx: int, paper_idx: int) -> str:
    """Deterministic arXiv-style id: ``arxiv:2401.NNNNN``.

    Cluster 0 → 00001..00008, cluster 1 → 00009..00016, etc.
    """
    sequence = cluster_idx * PAPERS_PER_CLUSTER + paper_idx + 1
    return f"arxiv:2401.{sequence:05d}"


def _render_paper_md(
    *,
    arxiv_id: str,
    title: str,
    cluster: dict[str, list[str]],
    referenced_concepts: list[str],
    referenced_topic: str,
    referenced_papers: list[str],
    author_slug: str,
) -> str:
    """Render a paper note. Paper templates live here for v0.4.0 because
    the existing ``Paper`` model + Obsidian reporter cover real digest
    output; this is fixture-only frontmatter sufficient for graph + lint
    tests.
    """
    parts: list[str] = []
    parts.append("---")
    parts.append("type: paper")
    parts.append(f"canonical_id: {arxiv_id}")
    parts.append(f"title: {title}")
    parts.append(f"cluster: {cluster['slug'][0]}")
    parts.append("---")
    parts.append("")
    parts.append(f"# {title}")
    parts.append("")
    parts.append(f"Synthetic fixture paper in the [[{referenced_topic}]] cluster.")
    parts.append("")
    parts.append("## Concepts")
    parts.append("")
    parts.extend(f"- [[{c}]]" for c in referenced_concepts)
    parts.append("")
    parts.append("## Related papers")
    parts.append("")
    parts.extend(f"- [[{p}]]" for p in referenced_papers)
    parts.append("")
    parts.append("## Author")
    parts.append("")
    parts.append(f"- [[{author_slug}]]")
    parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _build_cluster(
    rng: random.Random,
    cluster_idx: int,
    cluster: dict[str, list[str]],
    all_paper_ids_so_far: list[str],
) -> tuple[
    list[tuple[str, str]],  # (relpath, content) for papers
    list[tuple[str, str]],  # concepts
    list[tuple[str, str]],  # topics
    list[tuple[str, str]],  # people
]:
    cluster_papers: list[str] = [_arxiv_id(cluster_idx, i) for i in range(PAPERS_PER_CLUSTER)]

    # --- Concepts ---
    concept_files: list[tuple[str, str]] = []
    concepts_by_slug: dict[str, Concept] = {}
    for slug in cluster["concepts"]:
        # Each concept references 2-3 papers from this cluster.
        n_papers = rng.randint(2, 3)
        papers = rng.sample(cluster_papers, n_papers)
        concept = Concept(
            name=slug.replace("-", " ").title(),
            aliases=[slug.replace("-", "_")],
            definition=(
                f"Synthetic-fixture concept '{slug}' in the {cluster['slug'][0]} research cluster."
            ),
            tags=[cluster["slug"][0]],
            papers=papers,
        )
        concepts_by_slug[slug] = concept
        concept_files.append((f"concepts/{slug}.md", render_concept(concept, when=FIXTURE_WHEN)))

    # --- Topics ---
    topic_files: list[tuple[str, str]] = []
    for slug in cluster["topics"]:
        # Each topic references 2-3 papers + 2-3 concepts from this cluster.
        n_papers = rng.randint(2, 3)
        n_concepts = rng.randint(2, 3)
        papers = rng.sample(cluster_papers, n_papers)
        concepts = rng.sample(cluster["concepts"], n_concepts)
        topic = Topic(
            name=slug.replace("-", " ").title(),
            description=(
                f"Synthetic-fixture topic '{slug}' covering papers and "
                f"concepts in the {cluster['slug'][0]} cluster."
            ),
            papers=papers,
            concepts=concepts,
        )
        topic_files.append((f"topics/{slug}.md", render_topic(topic, when=FIXTURE_WHEN)))

    # --- People ---
    people_files: list[tuple[str, str]] = []
    for idx, slug in enumerate(cluster["people"]):
        # Each person authored 4-5 papers in their cluster.
        n_papers = rng.randint(4, 5)
        papers = rng.sample(cluster_papers, n_papers)
        # Collaborator: the OTHER person in this cluster.
        collaborators = [cluster["people"][1 - idx]]
        person = Person(
            name=slug.replace("-", " ").title(),
            aliases=[slug.replace("-", "_")],
            affiliation=f"Synthetic Fixture Inst {cluster_idx}",
            papers=papers,
            collaborators=collaborators,
        )
        people_files.append((f"people/{slug}.md", render_person(person, when=FIXTURE_WHEN)))

    # --- Papers ---
    # Each paper references its primary topic, 2 concepts, 1-2 other
    # papers (preferring within-cluster, occasionally cross-cluster).
    paper_files: list[tuple[str, str]] = []
    for paper_idx, arxiv_id in enumerate(cluster_papers):
        primary_topic = cluster["topics"][paper_idx % len(cluster["topics"])]
        # 2 concepts from this cluster.
        referenced_concepts = rng.sample(cluster["concepts"], 2)
        # 1-2 other papers; allow cross-cluster reference 30% of the time.
        candidate_papers = [p for p in cluster_papers if p != arxiv_id]
        if all_paper_ids_so_far and rng.random() < 0.3:
            candidate_papers = candidate_papers + all_paper_ids_so_far
        n_refs = rng.randint(1, 2)
        referenced_papers = rng.sample(candidate_papers, min(n_refs, len(candidate_papers)))
        author_slug = cluster["people"][paper_idx % len(cluster["people"])]
        title = f"Synthetic Paper {paper_idx + 1} on {primary_topic.replace('-', ' ').title()}"
        paper_files.append(
            (
                f"papers/{arxiv_id.replace(':', '-').replace('.', '-')}.md",
                _render_paper_md(
                    arxiv_id=arxiv_id,
                    title=title,
                    cluster=cluster,
                    referenced_concepts=referenced_concepts,
                    referenced_topic=primary_topic,
                    referenced_papers=referenced_papers,
                    author_slug=author_slug,
                ),
            )
        )

    return paper_files, concept_files, topic_files, people_files


def build(out_root: Path = FIXTURE_ROOT) -> dict[str, int]:
    """Build the fixture vault. Returns a per-subdir count summary."""
    # ``random.Random(SEED)`` is correct for deterministic test fixture
    # generation — no cryptographic property is required, only repeatable
    # output across runs (verified by builder-determinism CI gate).
    rng = random.Random(SEED)  # noqa: S311

    # Idempotent rebuild: wipe and re-create.
    if out_root.exists():
        shutil.rmtree(out_root)
    for subdir in ("papers", "concepts", "topics", "people"):
        (out_root / subdir).mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {
        "papers": 0,
        "concepts": 0,
        "topics": 0,
        "people": 0,
    }

    accumulated_paper_ids: list[str] = []
    timestamp = datetime(2026, 4, 30, tzinfo=UTC).isoformat()
    for cluster_idx, cluster in enumerate(CLUSTERS):
        papers, concepts, topics, people = _build_cluster(
            rng, cluster_idx, cluster, accumulated_paper_ids
        )
        for relpath, content in papers + concepts + topics + people:
            (out_root / relpath).write_text(content)
            counts[relpath.split("/", 1)[0]] += 1
        accumulated_paper_ids.extend(_arxiv_id(cluster_idx, i) for i in range(PAPERS_PER_CLUSTER))

    # Emit a small README so the fixture's purpose is discoverable when
    # reading via Obsidian.
    readme = (
        f"# synthetic_vault_100\n\n"
        f"Built {timestamp} via `tests/fixtures/build_synthetic_vault.py`\n"
        f"(seed={SEED}). Re-running the builder produces byte-identical\n"
        f"output. Notes split: papers={counts['papers']}, "
        f"concepts={counts['concepts']}, topics={counts['topics']}, "
        f"people={counts['people']}.\n\n"
        f"Used by 9.157 / 9.158 / Scenario 3 perf cliff / Scenario 5 "
        f"rollback round-trip tests.\n"
    )
    (out_root / "README.md").write_text(readme)

    return counts


if __name__ == "__main__":
    counts = build()
    total = sum(counts.values())
    print(f"built synthetic_vault_100: {counts} (total={total})")
