"""V8: corrective retrieval loop (CRAG style) as a small LangGraph.

retrieve -> grade -> (rewrite -> retrieve)* -> done
grade: a requirement is weak when its best cross-encoder score is below corrective.score_threshold.
rewrite: weak requirements are expanded with skills that co-occur with the best hit's skills in the
persona portfolio (the same vocabulary list_skills exposes). At most corrective.max_retries rewrites.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from rag.config import cfg
from rag.index.corpus import Corpus
from rag.query import requirement_name
from rag.variants.base import Pipeline


class CState(TypedDict, total=False):
    reqs: list[str]            # current query text per requirement
    ranked: list[list[tuple[str, float]]]
    weak: list[int]
    attempt: int


class V8Corrective:
    name = "v8_corrective"

    def __init__(self, corpus: Corpus, base: Pipeline | None = None):
        self.corpus = corpus
        self.base = base or Pipeline(corpus, name="v3_rerank", use_decompose=True, use_bm25=True,
                                     use_dense=True, use_rerank=True)
        self.rewrites = 0       # counters for reporting
        self.queries = 0
        self.graph = self._build()

    def _build(self):
        c = cfg()["corrective"]

        def retrieve(s: CState) -> CState:
            ranked = s.get("ranked") or [None] * len(s["reqs"])
            for i, r in enumerate(s["reqs"]):
                if ranked[i] is None or i in s.get("weak", []):
                    ranked[i] = self.base.rank_requirement(r)
            return {"ranked": ranked}

        def grade(s: CState) -> CState:
            weak = [i for i, r in enumerate(s["ranked"]) if not r or r[0][1] < c["score_threshold"]]
            return {"weak": weak}

        def rewrite(s: CState) -> CState:
            reqs = list(s["reqs"])
            for i in s["weak"]:
                top = self.corpus.by_id[s["ranked"][i][0][0]]
                name = requirement_name(s["reqs"][i])
                related = [x for x in top["skills"] if x.lower() != name.lower()][: c["related_skills"]]
                reqs[i] = f"{s['reqs'][i]}; related: {', '.join(related)}"
                self.rewrites += 1
            return {"reqs": reqs, "attempt": s.get("attempt", 0) + 1}

        def route(s: CState) -> str:
            return "rewrite" if s["weak"] and s.get("attempt", 0) < c["max_retries"] else END

        g = StateGraph(CState)
        g.add_node("retrieve", retrieve)
        g.add_node("grade", grade)
        g.add_node("rewrite", rewrite)
        g.add_edge(START, "retrieve")
        g.add_edge("retrieve", "grade")
        g.add_conditional_edges("grade", route, {"rewrite": "rewrite", END: END})
        g.add_edge("rewrite", "retrieve")
        return g.compile()

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        reqs = self.base.requirements(requirement)
        self.queries += 1
        out = self.graph.invoke({"reqs": reqs, "attempt": 0, "weak": []})
        return self.base.finish(self.base.merge(out["ranked"]), k, filters)
