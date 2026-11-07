# Cat re-identification evaluation

Facial recognition, but for cats. Before building the matching step, measure how well each method tells *individual* cats apart. The results decide which method `PLAN.md` §6c uses, which matches can be applied automatically, and what accuracy the demo claims.

## 1. Questions to answer

1. **Pick the right cat:** given a new photo and a colony's known cats (5–15), how often is the top choice right? How often is the right cat in the top 3?
2. **Spot a new cat:** when the cat in the photo is *not* on record, how often does the method correctly say "new"? Two kinds of mistake matter:
   - **False merge:** two different cats are made one. A cat disappears from the census, and possibly an unfixed one. **This is the worse error.**
   - **False split:** one cat is counted twice. That's the double-counting problem the brief names.
3. **Can we trust its confidence?** When a method says "high confidence," how often is it right? This sets the auto-merge threshold.
4. **Where does it break?** Break results down by coat type and photo conditions:
   - **coat:** distinctive (calico, tortoiseshell, bicolor, unusual markings), tabby, or solid (black, gray, white);
   - **view:** face or front, side, or back;
   - **light:** day or night/flash;
   - **framing:** full body, or partly hidden or far away.
5. **Cost and speed** for each new photo.

## 2. Test data

None of this is committed to the repo; it goes in a gitignored `eval_data/`. Record each source and its license in `eval_data/SOURCES.md`.

| source | what it is | use |
|---|---|---|
| **Our own photos** | real cats (ours, friends', street cats near the venue), 3–6 photos each, from different angles, light and days | **The main test set.** Closest to real volunteer photos. Ground truth is certain. Aim for 10–15 cats, including **several look-alikes**, such as two or more solid black or gray cats. |
| **Hello Street Cat** | 2,796 images of 69 street cats, used in a 2025 re-ID paper | A good match for our use case. Availability and license are unclear, so check the paper first. |
| **PetFace** (cats subset) | a large animal-face identity dataset with aligned face crops | Tests face-only matching. It's easier than real street photos, so don't use it alone. Check the license; it's probably research-only. Eval only, never in the demo. |
| **Feral cat re-ID paper** | camera-trap images of feral cats | Only if the data is released. It's night and IR-heavy, which is a hard case. |

**Collection rule for our own photos:** shoot the way a volunteer would, on a phone and not posed: some blurry, some from far away, some at night.

## 3. Methods to compare

| id | method | runs where | cost |
|---|---|---|---|
| **A** | OpenAI vision, **all photos in one call**: "group the same cats" | API | 1 large call |
| **B** | OpenAI vision, **per-colony gallery**: the new photo plus the colony's reference photos in one call → cat_id / new, confidence, deciding markings | API | 1 call per photo |
| **C** | OpenAI vision, **pairwise**: the new photo against each candidate → same / different / unsure | API | 1 call per candidate |
| **D** | **Describe, then compare text:** a vision call writes a structured description; text embeddings plus cosine similarity | API | 1 vision call + cheap embeddings |
| **E** | **Local re-ID embeddings:** [MegaDescriptor](https://arxiv.org/abs/2311.09118), a wildlife re-identification model on Hugging Face, plus a DINOv2 baseline; cosine similarity | local, free | none |
| **E-face** | E, but on a **cat-face crop** first (OpenCV `haarcascade_frontalcatface`, or a detector) | local | none |
| **F** | **Hybrid:** E picks the top 3 candidates, then B or C confirms with OpenAI | both | 1 call per photo |

Expected outcome: A breaks once there are more than about 15 photos. **F** is the likely winner, giving local embeddings' recall plus the vision model's ability to reason about markings and explain them, with one API call per photo. The test should confirm or overturn that.

The OpenAI API has text embeddings (`text-embedding-3-*`) but no documented image-embeddings endpoint, so D is the "OpenAI only" embedding option. Confirm this against the current docs.

## 4. Protocol

1. **Build simulated colonies.** For each trial, pick 8 cats. Give each 1–2 **reference** photos; the rest become **queries**.
   - About **20% of queries come from cats not in the colony**, which tests "new cat."
   - Include **hard colonies**, where every cat is a solid black or gray cat.
   - Use fixed random seeds, so every method sees the same trials.
2. **Run every method** on the same trials. Methods B, C and D return a confidence; E and F return a similarity score (and F also a confidence).
3. **Record per query:** the true cat (or "new"), the predicted cat (or "new"), the confidence or score, and cost and time.
4. Size: about 60 queries per method, which is enough to see differences without burning credits.

## 5. Metrics

- Top-1 and top-3 accuracy, for queries about known cats.
- New-cat recall, and the **false-merge rate**: different cats predicted as the same one.
- The **false-split rate:** the same cat predicted as "new."
- **Precision by confidence level** (the calibration from Question 3).
- **Auto-merge coverage:** the share of queries that can be applied without review at ≥95% precision.
- Cost per query and time per query.
- All of the above, broken down by coat type and photo condition.

## 6. Decision rule

Choose the method with the **highest auto-merge coverage at ≥95% precision** that fits the budget. Everything below the threshold goes to the review queue.

If no method reaches 95% even on distinctive cats, the product still works. Matching just becomes "suggest and confirm" for every photo, and the pitch says so honestly.

## 7. Budget

- Cap the API spend for this test at **$10** of the $50.
- Order: E and E-face (free) → D → B → F → C only if needed → A once, as the baseline.
- Resize images to about 768 px. Store the result of every call, keyed by a hash of the image plus the prompt, so re-runs are free.

## 8. Output

- `eval/run_eval.py --method B --trials 10 --seed 1`: one script, one method per run.
- `eval/results/<method>.csv`: one row per query.
- `eval/results/REPORT.md`: a table of methods × metrics, a breakdown by coat type, a gallery of the hardest misses (photo pairs), and the chosen method and threshold.
- **The report doubles as a pitch slide.** "We measured it: X% of photos are matched automatically at 95% precision, and the rest go to a volunteer." That speaks directly to judging criteria 3 (use of OpenAI) and 4 (feasibility).

## 9. Time box

About **2–2.5 hours total:** photos 45 min, harness 45 min, runs and report 45 min. If a dataset download or license check takes more than 15 minutes, drop that dataset and use our own photos.
