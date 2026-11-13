# My retrieval upgrades did nothing, and three of my wins were the answer key

I spent a day building a proposal drafting agent for freelance jobs and testing which retrieval pipeline gives it
the best evidence. I expected the fancy pipeline to win. It did not, and the more interesting result is how I
found out that several of my other improvements were not improvements either. Everything below is measured on
synthetic data in a simulator I built, so read it as a lesson about measurement, not about freelancing.

## The setup, briefly

GigBid reads a job post, decides whether to bid, and drafts a proposal that must cite real portfolio evidence for
every claim about past work. A human approves anything that is sent. There are three retrieval ideas I was sure
would help: split the job into its separate requirements and search for each (decomposition), combine keyword and
embedding search (hybrid), and rerank the candidates with a cross-encoder.

Before running anything I wrote down a prediction: decomposition plus hybrid plus rerank would raise Recall@5 by at
least 10 points over a plain embedding search on jobs with four or more requirements. The reasoning was simple. A
job with five requirements gives one embedding vector that blurs five topics, so a pipeline that searches per
requirement should find more of the right evidence.

## What happened

On 121 dev jobs, the full pipeline gained half a point on the four or more requirement jobs (95 percent interval
minus 1.0 to plus 2.0 points). It gained more, 5.3 points, on the easy one to three requirement jobs, which is the
opposite of my reasoning. Dense search alone had a Recall@5 of 0.359. My best pipeline had 0.385. The reranker
that gave that small lift added about seven seconds of retrieval latency at the 95th percentile, against roughly
a tenth of a second for plain dense search.

I shipped the hybrid retriever, the cheapest option that was never worse than the baseline, and moved on. The
downstream numbers did not separate the variants either: the judge score was 3.56 for the baseline and 3.59 for
the reranked version, and the reranked version had the lower simulated reply rate (0.24 against 0.39, but that is
17 and 18 proposals, so it is noise and I say so).

## The part that bothered me

A flat result is easy to accept. What bothered me was a second table. When I removed one component at a time from
the best pipeline, the decomposition step cost almost nothing, which was my favourite idea. So I asked a question I
should have asked earlier: how does my decomposition step know what the requirements are?

It reads a line. Every synthetic job post my generator writes contains the literal text "Required: A, B, C." And the
gold label for what evidence is correct is built from the same list of skills. My decomposition step was reading
the answer key.

I added an ablation row that decomposes without that line, splitting by sentences and commas like a real system
would have to. Recall@5 dropped to 0.355 and nDCG@10 to 0.884. That is worse than the plain dense baseline. So the
most honest reading of my own result is that decomposition looked neutral only because it was partly cheating, and
without the leak it hurts.

This is the first thing I would tell anyone building an evaluation set from a generator: if the same code writes
the inputs and the labels, assume the system can find the shared structure, and build an ablation that removes it.

## The second answer key: my "improvement"

Later I ran a small exercise: a platform rule changes (jobs under 50 dollars are not accepted, Connects cost goes
up by half, external links are banned) and I measure how much code that takes. The answer was pleasing. No agent
code changed, only a policy file and a test. It took under four minutes. And the bid or skip F1 score went up,
from 0.75 to 0.89 on one persona and from 0.77 to 0.94 on another.

I wanted to believe that was a better decision rule. It was not. I checked the budgets of the synthetic jobs that
my generator labels as low paying "lowball" jobs. All 30 of them have a budget of exactly 40 dollars. The new
minimum of 50 dollars sits just above that, so the rule removes them by construction and the metric rises. The part
of the result that is real is the cheap absorption of the change, which comes from reading policy at run time
instead of hard coding it. The part that is not real is the score.

## What did matter

Two things moved the numbers for reasons I trust, because neither depends on my generator's quirks.

The first is a claim verifier that runs before the reviewing step. It splits a draft into sentences, and any
sentence about past work that does not cite an evidence item I actually retrieved is removed. Unsupported claims per
proposal went from 0.33 to 0.00 for the baseline and from 0.59 to 0.00 for the reranked variant. It is a structural
check, so it does not care which retriever produced the evidence. It is also weaker than it sounds. It checks that
a cited identifier exists, not that the sentence says only what the evidence says. A stricter audit I wrote, which
also checks that numbers match, still finds 0.12 unsupported claims per proposal in the reranked drafts. I would
rather report that residue than claim zero.

The second is the shape of the system. I compared a single ReAct agent with every tool, a supervisor setup, and my
hand built graph, all running the same local 7 billion parameter model on the same 30 jobs. The graph decided bid
or skip correctly 67 percent of the time against 23 percent for ReAct and 60 percent for the supervisor, produced no
unsupported claims where the others produced 0.64 and 0.88 per letter, and used about 2,000 tokens per job against
23,500 for ReAct. That is twelve times fewer tokens.

It is not a clean victory, and the table is more useful than the headline. ReAct was the fastest, with a median of 18
seconds against 37 for the graph. The supervisor scored 0.8 on the lowball jobs where the graph scored zero, but it
scored zero on the good jobs. It wins that column by almost never bidding, which is a policy, not a skill. The graph's
real weakness is that it bids on everything that looks relevant.

## What I would do differently

Build the leak check first. Before running a single variant, I would write the version of each pipeline that has no
access to the generator's structure and treat that as the real baseline. It would have saved a day of believing
decomposition worked.

Size the experiments honestly. I ran on free tiers, so my samples are 17 to 40 per comparison. My proposal strategy
A/B test, evidence first against outcome and timeline first, ended with reply rates of 26 percent and 15 percent. The
two proportion test gave p equals 0.38, and the test could only detect a difference of about 36 points. A real gap
of up to a third could have been missed. I report it as inconclusive, not as "no effect". Detecting a 10 point
difference would need on the order of 250 proposals per arm.

Do not let the judge score stand in for quality. I calibrated my LLM judge on 30 drafts and got a quadratic kappa
of 0.59 with 70 percent exact agreement, which is moderate at best. The reference labels came from a second LLM, not
a person, so that number says two models mostly agree, not that either is right. The 3.56 against 3.59 comparison
above is far inside that noise and carries no weight in any direction.

## The takeaway

Three of the four things I was proudest of, decomposition, the cheap policy change, and the scam detection I have
not discussed here (its precision and recall are both 1.0 because my scam templates and my detection patterns were
written from the same list), were partly the evaluation measuring my generator. The things that survived scrutiny
were boring: a check that deletes unsupported sentences, a graph that spends about a twelfth of the tokens, and a habit of
asking, for every good number, what in my own data could have produced it.

Code, results files and the public traces are in the repository. Every number above is copied from a file under
`evals/results/`.
