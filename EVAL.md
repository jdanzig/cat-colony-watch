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
| **E** | **Feature verdicts plus a rule:** like B, but the model returns a per-feature same / different / not visible for each candidate (`PLAN.md` §6c), and **code** decides | API | 1 call per photo |
| **F** | **Hybrid:** D's text-embedding ranking keeps the top 3, then E confirms | API | 1 call + cheap embeddings |

**Everything runs on the OpenAI API;** no local models. Cropping is the only local image step.

**Cropping applies to every method.** The description call returns each cat's bounding box, and Pillow crops it. Run B and E both **with and without cropping**, because a shared background (the same wall or dumpster) can make two different cats look like a match.

Expected outcome: A breaks once there are more than about 15 photos. **E or F** is the likely winner: a rule over specific observations should be easier to trust than the model's own confidence, and each decision comes with its reason. The test should confirm or overturn that.

The OpenAI API has text embeddings (`text-embedding-3-*`) but no documented image-embeddings endpoint, so D is the "OpenAI only" embedding option. Confirm this against the current docs.

## 4. Protocol

1. **Build simulated colonies.** For each trial, pick 8 cats. Give each 1–2 **reference** photos; the rest become **queries**.
   - About **20% of queries come from cats not in the colony**, which tests "new cat."
   - Include **hard colonies**, where every cat is a solid black or gray cat.
   - Use fixed random seeds, so every method sees the same trials.
2. **Run every method** on the same trials. B and C return the model's own confidence; D returns a similarity score; E and F return the rule's decision plus the feature verdicts behind it.
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
- Order: D (cheapest) → B → E → F → C only if needed → A once, as the baseline. Run B and E with and without cropping.
- Resize images to about 768 px. Store the result of every call, keyed by a hash of the image plus the prompt, so re-runs are free.

## 8. Output

- `eval/run_eval.py --method B --trials 10 --seed 1`: one script, one method per run.
- `eval/results/<method>.csv`: one row per query.
- `eval/results/REPORT.md`: a table of methods × metrics, a breakdown by coat type, a gallery of the hardest misses (photo pairs), and the chosen method and threshold.
- **The report doubles as a pitch slide.** "We measured it: X% of photos are matched automatically at 95% precision, and the rest go to a volunteer." That speaks directly to judging criteria 3 (use of OpenAI) and 4 (feasibility).

## 9. Time box

About **2–2.5 hours total:** photos 45 min, harness 45 min, runs and report 45 min. If a dataset download or license check takes more than 15 minutes, drop that dataset and use our own photos.
