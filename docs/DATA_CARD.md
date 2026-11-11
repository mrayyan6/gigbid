# Data Card

Status: final for submission. Every record in the system is **synthetic**. No real Upwork or Kaggle
data is used in any reported result.

## What the data is

Generated deterministically by `gigsim/generate.py` (seed 7, `python -m gigsim.generate`, output in
`data/processed/gigsim/`, git-ignored and rebuilt on demand).

| File | Rows | Content |
|---|---|---|
| personas.json | 3 | AI/ML engineer, full-stack web developer, data analyst (rate, skills, projects) |
| portfolio.json | 48 | 16 portfolio items per persona (case studies with skills, outcome, date), about 30 words each |
| past_proposals.json | 360 | Labelled past proposals with outcomes |
| clients.json | 40 | Clients with hidden preferences and history |
| jobs.json | 360 | Job stream (130 good, 59 stretch, 45 inject, 43 scam, 42 offtopic, 41 lowball) |
| dev_jobs.json | 180 | Dev evaluation subset, 60 per persona, with gold labels (action, kind, scam, injected, required skills) |

Every synthetic record carries `"source": "synthetic"`.

## Why not the Kaggle datasets

The instructor allowed six Kaggle datasets (listed in `scripts/fetch_datasets.py`). The fetch needs a
Kaggle API token, which was not set up, so `data/raw/` is empty and nothing from those datasets is used.
The fetch script is kept so the datasets can be added later. Licences, row counts and attribution for them
are therefore NOT claimed here. If they are added, this card must be updated with licence, rows and
limitations for each.

## Gold labels and how they are made

- Bid, watch or skip is set by the job kind at generation time (good bid, stretch watch, offtopic, scam,
  inject and lowball skip).
- Gold evidence for retrieval is the set of persona portfolio items whose skill tags include at least one
  required skill of the job.
- Scam and inject jobs are produced from templates, injection payloads are planted strings.

## Limitations (read before trusting any number)

1. **Circular labels.** Scam jobs come from templates and the risk patterns that detect them were written
   against the same wording, so scam precision and recall of 1.0 say little about real scams.
2. **Circular retrieval gold.** The gold evidence is skill tag membership, the chunk text repeats the tags,
   and every job text contains a literal "Required: a, b, c." line that equals the gold skill list.
   Decomposition variants (V1, V3, V8) partly read the answer key. The ablation includes a `no_marker` row
   that decomposes without that line.
3. **Tiny corpus.** 16 items per persona, so one chunk per item and fixed size chunking is not exercised.
4. **Simulated outcomes.** GigSim reply and hire draws are pseudo random from a formula we wrote. Reply
   rates measure behaviour inside our simulator, not real clients.
5. **Small samples.** LLM based evaluations use 17 to 40 items, so confidence intervals are wide. Each
   results file records its n.
6. **Synthetic text style.** Jobs and proposals are templated and far more regular than real postings.

## Personal data

None. Names are invented. The reviewer account and any tokens are created at deploy time from environment
variables and are never committed.

## Licence

No LICENSE file has been added yet (open decision for the owner). No third party
data is redistributed.
