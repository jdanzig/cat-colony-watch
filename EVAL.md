# Cat identification check

Facial recognition, but for cats. This check runs **the app's own** `describe_photo()` and `match_cat()` (`PLAN.md` §7) on photos where we already know which cat is which. Build it with the matching code, and re-run it every time a prompt or rule changes. It tells us whether a change helped, which matches can be applied automatically, and what accuracy the demo can honestly claim.

## 1. What it answers

1. **Pick the right cat:** given a photo and a colony's known cats (5–15), how often is the match correct?
2. **Spot a new cat:** when the cat isn't on record, how often does it say "new"? Two kinds of mistake matter:
   - **False merge:** two different cats are made one. A cat disappears from the census, and possibly an unfixed one. **This is the worse error.**
   - **False split:** one cat is counted twice. That's the double-counting problem the brief names.
3. **How often it asks a person:** the share of photos sent to review. A low false-merge rate with a reasonable review rate is the goal.
4. **Where it breaks:**
   - **coat:** distinctive (calico, tortoiseshell, bicolor, unusual markings), tabby, or solid (black, gray, white);
   - **view:** face, side or back.
5. **Cost** per photo.

## 2. Test photos

`eval_data/commons/` (gitignored) holds **306 photos of 41 individual named cats** from Wikimedia Commons, up to 8 per cat, downscaled to 768 px.
- Each cat has its own folder, so we know which cat each photo shows.
- `manifest.json` and `SOURCES.md` list each photo's source page, license and author.
- They include look-alikes:
  - red tabbies: Rum Tum Tugger, Caramel, Peach;
  - solid black cats: Cola, Miss Kitty;
  - breed twins: two "Asian cat" entries, a Ragdoll, a Sphynx, a Bengal.

**Before first use,** do a quick visual pass. Drop anything that doesn't clearly show the cat, such as drawings, letters, close-ups of an eye or nose, or group photos. Cats with fewer than 4 usable photos are used only as "new cat" queries.

**Limits to say out loud:** these are mostly pet photos, indoors and well lit. Real volunteer photos are street cats at a distance, at night, partly hidden. If time allows, add a few harder photos: Commons street-cat categories, or photos of neighborhood cats taken near the venue.

## 3. How a run works

1. **Simulate colonies.** For each trial, pick 8 cats. Give each 1–2 **reference** photos; the rest become **queries**.
   - About **20% of queries come from cats not in the colony,** which tests "new cat."
   - Include **hard colonies** made up of look-alikes, such as all the red tabbies or both black cats.
   - Use fixed random seeds, so runs before and after a change are comparable.
2. **Run** `describe_photo()` and `match_cat()` on each query, exactly as the app does: same prompts, same cropping, same decision rule.
3. **Record** for each query: the true cat (or "new"), the decision (match / new / review), the feature verdicts and the cost.

`eval/check_matching.py --cats 5 --seed 1` runs a small check. `--cats all` runs the full set.

## 4. Numbers it prints

- **Correct-match rate** on the automatic decisions.
- **False-merge rate** and **false-split rate**.
- **Review rate:** the share sent to a person.
- The same three, broken down by coat type.
- **Cost per photo** and the total for the run.
- The **5 worst mistakes,** as photo pairs with the feature verdicts. These show what to fix in the prompt or the rule.

Append each run to `eval/results/REPORT.md` with the date, what changed and the numbers, so the history shows whether each change helped.

## 5. The loop

1. Run a small check (5 cats, about $0.50).
2. Look at the worst mistakes, then change **one thing**: the prompt wording, which features are asked for, the rule thresholds, or cropping on or off.
3. Re-run the same seed and keep the change only if the false-merge rate didn't get worse.
4. Once the small check looks good, run the full set **once**.

**Target:** false merges near 0% on automatic decisions, and as many automatic decisions as possible. **The rule is: when in doubt, ask a person.** If the review rate is high, the product still works and the pitch says so honestly: "it handles the easy 60% and asks about the rest."

## 6. Optional: compare other methods

Only if the core loop is working and there's spare time and credit. Compare the main method with:
- all photos in one call (the baseline we expect to break);
- the model picking a match by itself, with its own confidence and no feature rule;
- text descriptions compared with text embeddings (cheap).

That gives one pitch slide: "We tested four ways; feature verdicts plus a rule made the fewest false merges."

## 7. Budget

- **$10 at most** of the $50 for all checking runs combined.
- Cache every API result by a hash of the image plus the prompt version, so re-running unchanged cases is free. Only changed prompts cost money.
- Resize to about 768 px before sending.
