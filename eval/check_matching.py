#!/usr/bin/env python3
"""Run the app's cat-identification functions on known Wikimedia cats."""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.identification import describe_photo, match_cat  # noqa: E402


COMMONS = ROOT / "eval_data" / "commons"
CACHE = ROOT / "eval" / "cache"
REPORT = ROOT / "eval" / "results" / "REPORT.md"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
# Visual pass: drawings, extreme close-ups, group photos, or photos without a
# clearly visible cat. Kept here rather than modifying the downloaded corpus.
EXCLUDED_PHOTOS = {
    "bella-cat/01.jpg",
    "cola-solid-black-cat/07.jpg",
    "doraemon-cat/01.jpg",
    "doraemon-cat/05.jpg",
    "doraemon-cat/06.jpg",
    "doraemon-cat/07.jpg",
    "doraemon-cat/08.jpg",
    "erik-the-cat-sk-lsk-r/05.jpg",
    "foss-cat/01.jpg",
    "ms-squeaky-cat/04.jpg",
    "miss-truffles-cat/04.jpg",
    "onapromise-pyanfar-cat/05.jpg",
    "prickles-asian-cat/01.jpg",
    "rum-tum-tugger-red-tabby-cat/01.jpg",
    "rum-tum-tugger-red-tabby-cat/02.jpg",
    "rum-tum-tugger-red-tabby-cat/03.jpg",
    "socks-cat/05.jpg",
    "suzieq-cat/01.jpg",
    "suzieq-cat/05.jpg",
    "uthello-sphynx-cat/01.jpg",
    "uthello-sphynx-cat/05.jpg",
    "v-kingur-nfo-cat/02.jpg",
    "v-kingur-nfo-cat/05.jpg",
    "v-kingur-nfo-cat/06.jpg",
    "v-kingur-nfo-cat/08.jpg",
}
HARD_COLONY = [
    "caramel-red-tabby-cat",
    "rum-tum-tugger-red-tabby-cat",
    "cola-solid-black-cat",
    "miss-kitty-black-silver-cat",
    "leerie-asian-cat",
    "prickles-asian-cat",
    "osiris-bengal-cat",
    "tesla-ragdoll-cat",
]
TUNING_CATS = {
    "erik-the-cat-sk-lsk-r",
    "tomcat-matata-cat",
    "cola-solid-black-cat",
    "loki-cat",
    "ellie-cat",
}


def photo_files(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.iterdir()
        if path.suffix.lower() in IMAGE_SUFFIXES
        and f"{folder.name}/{path.name}" not in EXCLUDED_PHOTOS
    )


def ensure_data() -> None:
    if COMMONS.exists() and any(path.is_dir() for path in COMMONS.iterdir()):
        return
    subprocess.run([sys.executable, str(ROOT / "eval" / "fetch_commons.py")], check=True)


def choose_cats(
    count: str, seed: int, hard_colony: bool = False
) -> tuple[list[Path], list[Path]]:
    usable = sorted(
        path for path in COMMONS.iterdir() if path.is_dir() and len(photo_files(path)) >= 4
    )
    if count == "all":
        return usable, []
    wanted = int(count)
    if wanted < 2 or wanted > len(usable):
        raise ValueError(f"--cats must be 2..{len(usable)} or all")
    rng = random.Random(seed)
    forced = [path for path in usable if hard_colony and path.name in HARD_COLONY]
    if len(forced) > wanted:
        raise ValueError(f"--cats must be at least {len(forced)} with --hard-colony")
    remaining = [path for path in usable if path not in forced]
    selected = forced + rng.sample(remaining, wanted - len(forced))
    return selected, [path for path in usable if path not in selected]


def build_trials(
    selected: list[Path], unselected: list[Path], count: str, seed: int
) -> list[dict[str, Any]]:
    """Make reproducible simulated colonies with about 20% new-cat queries."""
    rng = random.Random(seed)
    if count == "all" or len(selected) > 8:
        by_name = {path.name: path for path in selected}
        hard = [by_name.pop(name) for name in HARD_COLONY if name in by_name]
        remaining = list(by_name.values())
        rng.shuffle(remaining)
        ordered = hard + remaining
        colony_groups = [ordered[index : index + 8] for index in range(0, len(ordered), 8)]
    else:
        colony_groups = [selected]

    all_folders = sorted(
        path for path in COMMONS.iterdir() if path.is_dir() and photo_files(path)
    )
    trials = []
    for trial_number, colony in enumerate(colony_groups):
        references: dict[str, list[Path]] = {}
        queries: list[tuple[Path, str]] = []
        for folder in colony:
            photos = photo_files(folder)
            rng.shuffle(photos)
            references[folder.name] = photos[:2]
            queries.extend((path, folder.name) for path in photos[2:])

        new_count = math.ceil(len(queries) / 4)
        if len(colony_groups) == 1:
            new_pool = unselected
        else:
            colony_names = set(references)
            new_pool = [path for path in all_folders if path.name not in colony_names]
        for folder in rng.sample(new_pool, min(new_count, len(new_pool))):
            queries.append((rng.choice(photo_files(folder)), "new"))
        rng.shuffle(queries)
        trials.append(
            {"number": trial_number + 1, "cats": colony, "references": references, "queries": queries}
        )
    return trials


def coat_group(description: dict[str, Any]) -> str:
    pattern = description["cats"][0]["pattern"]
    if pattern == "tabby":
        return "tabby"
    if pattern == "solid":
        return "solid"
    return "distinctive"


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def add_cost(total: float, result: dict[str, Any], limit: float) -> float:
    cost = result.get("_meta", {}).get("run_cost_usd")
    if cost is None:
        raise RuntimeError("model price is unknown; refusing a paid run without a cost estimate")
    total += float(cost)
    # Leave headroom for one response whose usage is known only after it returns.
    if total >= limit * 0.95:
        raise RuntimeError(
            f"stopped at ${total:.4f}, before the ${limit:.2f} run cap; ask before continuing"
        )
    return total


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strong = [row for row in rows if row["suggestion"] == "strong"]
    correct_strong = [row for row in strong if row["candidate_id"] == row["truth"]]
    wrong_strong = [row for row in strong if row["candidate_id"] != row["truth"]]
    known = [row for row in rows if row["truth"] != "new"]
    false_splits = [row for row in known if row["suggestion"] == "new"]
    new_queries = [row for row in rows if row["truth"] == "new"]
    correct_new = [row for row in new_queries if row["suggestion"] == "new"]
    return {
        "queries": len(rows),
        "strong_precision": ratio(len(correct_strong), len(strong)),
        "wrong_strong_rate": ratio(len(wrong_strong), len(rows)),
        "false_split_rate": ratio(len(false_splits), len(known)),
        "strong_rate": ratio(len(strong), len(rows)),
        "weak_rate": ratio(sum(row["suggestion"] == "weak" for row in rows), len(rows)),
        "new_cat_recall": ratio(len(correct_new), len(new_queries)),
        "strong_count": len(strong),
        "weak_count": sum(row["suggestion"] == "weak" for row in rows),
        "wrong_strong_count": len(wrong_strong),
        "false_split_count": len(false_splits),
        "known_count": len(known),
        "new_count": len(new_queries),
        "correct_new_count": len(correct_new),
    }


def mistake_rank(row: dict[str, Any]) -> tuple[int, str]:
    if row["suggestion"] == "strong" and row["candidate_id"] != row["truth"]:
        return (0, str(row["query"]))
    if row["truth"] != "new" and row["suggestion"] == "new":
        return (1, str(row["query"]))
    if row["suggestion"] == "weak" and row["candidate_id"] != row["truth"]:
        return (2, str(row["query"]))
    return (9, str(row["query"]))


def append_report(
    args: argparse.Namespace,
    selected: list[Path],
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    held_out: dict[str, Any],
    groups: dict[str, dict[str, Any]],
    cost: float,
) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    if not REPORT.exists():
        REPORT.write_text("# Matching check results\n\n")
    lines = [
        f"## {date.today().isoformat()} — {args.note}",
        "",
        f"- Model: `{args.model}`",
        f"- Command: `python eval/check_matching.py --cats {args.cats} --seed {args.seed}{' --hard-colony' if args.hard_colony else ''}`",
        f"- Cats: {', '.join(path.name for path in selected)}",
        f"- Queries: {summary['queries']}",
        f"- Strong precision: {pct(summary['strong_precision'])} ({summary['strong_count'] - summary['wrong_strong_count']}/{summary['strong_count']})",
        f"- Wrong-strong rate: {pct(summary['wrong_strong_rate'])} ({summary['wrong_strong_count']}/{summary['queries']})",
        f"- False-split rate: {pct(summary['false_split_rate'])} ({summary['false_split_count']}/{summary['known_count']})",
        f"- Strong rate: {pct(summary['strong_rate'])} ({summary['strong_count']}/{summary['queries']})",
        f"- Weak rate: {pct(summary['weak_rate'])} ({summary['weak_count']}/{summary['queries']})",
        f"- New-cat recall: {pct(summary['new_cat_recall'])} ({summary['correct_new_count']}/{summary['new_count']})",
        f"- Held-out queries (excluding the five tuning cats): {held_out['queries']}",
        f"- Held-out strong precision: {pct(held_out['strong_precision'])} ({held_out['strong_count'] - held_out['wrong_strong_count']}/{held_out['strong_count']})",
        f"- Held-out wrong-strong rate: {pct(held_out['wrong_strong_rate'])} ({held_out['wrong_strong_count']}/{held_out['queries']})",
        f"- Held-out false-split rate: {pct(held_out['false_split_rate'])} ({held_out['false_split_count']}/{held_out['known_count']})",
        f"- Held-out strong rate: {pct(held_out['strong_rate'])} ({held_out['strong_count']}/{held_out['queries']})",
        f"- Held-out weak rate: {pct(held_out['weak_rate'])} ({held_out['weak_count']}/{held_out['queries']})",
        f"- Held-out new-cat recall: {pct(held_out['new_cat_recall'])} ({held_out['correct_new_count']}/{held_out['new_count']})",
        f"- Run cost: ${cost:.4f} (${cost / len(rows):.4f} per query photo)",
        "",
        "| coat | queries | strong precision | wrong strong | false split | strong rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in ("distinctive", "tabby", "solid"):
        item = groups.get(group, metrics([]))
        lines.append(
            f"| {group} | {item['queries']} | {pct(item['strong_precision'])} | "
            f"{pct(item['wrong_strong_rate'])} | {pct(item['false_split_rate'])} | {pct(item['strong_rate'])} |"
        )
    lines.extend(["", "Worst mistakes:", ""])
    mistakes = [row for row in sorted(rows, key=mistake_rank) if mistake_rank(row)[0] < 9][:5]
    if not mistakes:
        lines.append("- None.")
    for row in mistakes:
        lines.append(
            f"- `{row['query']}`: truth `{row['truth']}`, got {row['suggestion']} "
            f"`{row['candidate_id']}`; references: "
            f"{', '.join(f'`{path}`' for path in row['candidate_references'])}. "
            f"Verdicts: `{json.dumps(row['comparisons'], sort_keys=True)}`"
        )
    REPORT.write_text(REPORT.read_text() + "\n".join(lines) + "\n\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cats", default="5", help="number of cats, or all")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--model", default="gpt-6.1-terra")
    parser.add_argument("--max-cost", type=float, default=1.0)
    parser.add_argument("--note", default="initial feature-verdict rule")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument(
        "--hard-colony",
        action="store_true",
        help="force the known look-alike cats into the sample and one colony",
    )
    args = parser.parse_args()

    ensure_data()
    selected, unselected = choose_cats(args.cats, args.seed, args.hard_colony)
    print("Selected cats:", ", ".join(path.name for path in selected), flush=True)
    trials = build_trials(selected, unselected, args.cats, args.seed)
    for trial in trials:
        print(
            f"Colony {trial['number']}: "
            + ", ".join(path.name for path in trial["cats"]),
            flush=True,
        )
    if args.dry_run:
        return

    total_cost = 0.0
    descriptions: dict[Path, dict[str, Any]] = {}
    all_photos = {
        path
        for trial in trials
        for paths in trial["references"].values()
        for path in paths
    } | {path for trial in trials for path, _ in trial["queries"]}
    print(f"Describing {len(all_photos)} unique photos...", flush=True)
    for number, photo in enumerate(sorted(all_photos), 1):
        result = describe_photo(photo, model=args.model, cache_dir=CACHE)
        total_cost = add_cost(total_cost, result, args.max_cost)
        if result["cat_count"] < 1:
            raise RuntimeError(f"no cat found in {photo}")
        descriptions[photo] = result
        print(f"  {number}/{len(all_photos)} ${total_cost:.4f}", end="\r", flush=True)
    print()

    candidates_by_trial = {}
    for trial in trials:
        candidates_by_trial[trial["number"]] = [
            {
                "id": cat_id,
                "reference_photos": photos,
                "reference_descriptions": [descriptions[path] for path in photos],
            }
            for cat_id, photos in trial["references"].items()
        ]

    rows = []
    query_count = sum(len(trial["queries"]) for trial in trials)
    print(f"Matching {query_count} query photos...", flush=True)
    numbered_queries = (
        (trial, query, truth)
        for trial in trials
        for query, truth in trial["queries"]
    )
    for number, (trial, query, truth) in enumerate(numbered_queries, 1):
        result = match_cat(
            query,
            candidates_by_trial[trial["number"]],
            query_description=descriptions[query],
            model=args.model,
            cache_dir=CACHE,
        )
        total_cost = add_cost(total_cost, result, args.max_cost)
        candidate_id = result["candidate_id"]
        candidate_refs = trial["references"].get(candidate_id, [])
        rows.append(
            {
                "query": query.relative_to(ROOT),
                "source_cat": query.parent.name,
                "truth": truth,
                "suggestion": result["suggestion"],
                "candidate_id": candidate_id,
                "coat": coat_group(descriptions[query]),
                "candidate_references": [path.relative_to(ROOT) for path in candidate_refs],
                "comparisons": result.get("comparisons", []),
            }
        )
        print(f"  {number}/{query_count} ${total_cost:.4f}", end="\r", flush=True)
    print()

    summary = metrics(rows)
    held_out_rows = [row for row in rows if row["source_cat"] not in TUNING_CATS]
    held_out = metrics(held_out_rows)
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped_rows[row["coat"]].append(row)
    groups = {name: metrics(items) for name, items in grouped_rows.items()}

    print(f"All-cats queries:             {summary['queries']}")
    print(f"All-cats strong precision:    {pct(summary['strong_precision'])}")
    print(f"All-cats wrong-strong rate:   {pct(summary['wrong_strong_rate'])}")
    print(f"All-cats false-split rate:    {pct(summary['false_split_rate'])}")
    print(f"All-cats strong rate:         {pct(summary['strong_rate'])}")
    print(f"All-cats weak rate:           {pct(summary['weak_rate'])}")
    print(f"All-cats new-cat recall:      {pct(summary['new_cat_recall'])}")
    print(f"Held-out queries:    {held_out['queries']}")
    print(f"Held-out strong precision:  {pct(held_out['strong_precision'])}")
    print(f"Held-out wrong-strong rate: {pct(held_out['wrong_strong_rate'])}")
    print(f"Held-out false-split rate:  {pct(held_out['false_split_rate'])}")
    print(f"Held-out strong rate:       {pct(held_out['strong_rate'])}")
    print(f"Held-out weak rate:         {pct(held_out['weak_rate'])}")
    print(f"Held-out new-cat recall:    {pct(held_out['new_cat_recall'])}")
    print(f"Run cost:            ${total_cost:.4f} (${total_cost / len(rows):.4f}/query)")
    for group in ("distinctive", "tabby", "solid"):
        item = groups.get(group, metrics([]))
        print(
            f"{group:12} n={item['queries']:2} strong_precision={pct(item['strong_precision']):>6} "
            f"wrong_strong={pct(item['wrong_strong_rate']):>6} "
            f"false_split={pct(item['false_split_rate']):>6} strong_rate={pct(item['strong_rate']):>6}"
        )
    if not args.no_report:
        append_report(args, selected, rows, summary, held_out, groups, total_cost)
        print(f"Appended results to {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
