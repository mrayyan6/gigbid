# Data Card

Status: draft. Licences, row counts and limitations to be filled after download and inspection.

## Real data sources (Kaggle, fetched by scripts/fetch_datasets.py into data/raw/, git-ignored)

| Local name | Kaggle slug | Planned use | Licence | Rows | Limitations |
|---|---|---|---|---|---|
| upwork_jobs_50k | asaniczka/upwork-job-postings-dataset-2024-50k-records | Job stream, skills, budgets | TODO | TODO | TODO |
| upwork_jobs_200k | asaniczka/all-jobs-on-upwork-200k-plus | Historical jobs, category mix | TODO | TODO | TODO |
| upwork_jobs_60k | ahmedmyalo/upwork-freelance-jobs-60k | Job stream, pricing bands | TODO | TODO | TODO |
| freelance_contracts_1_3m | asaniczka/freelance-contracts-dataset-1-3-million-entries | Rate and outcome priors for simulator | TODO | TODO | TODO |
| freelancer_earnings_churn | sarveshchhetri/freelancer-success-earnings-and-churn-prediction | Success and earnings priors | TODO | TODO | TODO |
| trial_1 | adityammantri/trial-1 | Unknown, inspect before use | TODO | TODO | TODO |

## Synthetic data (must be labelled synthetic everywhere)

Generated where real data is unavailable: freelancer personas and portfolios, client histories,
reviews, past proposals, client conversations, scam and prompt-injection jobs, hidden client
preferences for the simulator. Every synthetic record carries `"source": "synthetic"`;
real-derived records carry `"source": "kaggle:<local name>"`.

## Preprocessing
TODO: cleaning, dedup, PII removal, mapping into GigSim job schema, output in data/processed/.

## Attribution
TODO: cite each dataset author and licence terms before submission.
