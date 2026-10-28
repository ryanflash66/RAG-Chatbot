# RAG metrics: what we measure and how (DAR-637)

The NCDOT division assistant is a retrieval-augmented generation (RAG) system. It finds passages in one division's manual, then has a language model answer from those passages only. A RAG system can fail in two places: the search can bring back the wrong passages, or the model can misuse the right ones. The standard metrics measure each part separately, which shows where a failure comes from.

We use the four RAGAS metrics, which are the most widely used RAG metric set, plus answer time. RAGAS stands for Retrieval Augmented Generation Assessment. As a cross-check that doesn't depend on a language model, we also compare retrieval with the PDF pages known to hold each answer.

| Dr. Namian's question (Oct 22) | Metric |
|---|---|
| Is the answer accurate? | Faithfulness, answer relevancy (LLM-as-a-judge) |
| Does it retrieve irrelevant information? | Context precision (and page precision) |
| Does it miss important information? | Context recall (and page recall, hit@5) |
| How fast is it? | Answer time, total and per step |

## Sources

- **RAGAS paper.** S. Es, J. James, L. Espinosa-Anke and S. Schockaert, "RAGAs: Automated Evaluation of Retrieval Augmented Generation", *EACL 2024 System Demonstrations*, pp. 150-158. [aclanthology.org/2024.eacl-demo.16](https://aclanthology.org/2024.eacl-demo.16), preprint [arXiv:2309.15217](https://arxiv.org/abs/2309.15217). It splits RAG quality into retrieving relevant, focused passages, the model using them faithfully, and the quality of the answer itself. It also defines faithfulness and answer relevance as LLM-judged scores.
- **RAGAS documentation**, "Available metrics" (docs.ragas.io), retrieved 2026-10-27, for the current definitions:
  [Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/),
  [Answer relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/),
  [Context precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/),
  [Context recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/).
- **RAGAS source code** for details the docs leave out: answer relevancy generates 3 questions by default (`strictness = 3`) and scores 0 when the answer is noncommittal (`score = cosine_sim.mean() * int(not all_noncommittal)`), in [`src/ragas/metrics/_answer_relevance.py`](https://github.com/explodinggradients/ragas/blob/main/src/ragas/metrics/_answer_relevance.py).
- **Refusing when the documents don't answer.** J. Chen, H. Lin, X. Han and L. Sun, "Benchmarking Large Language Models in Retrieval-Augmented Generation", *AAAI 2024*, [arXiv:2309.01431](https://arxiv.org/abs/2309.01431). This paper names *negative rejection* as one of four abilities a RAG model needs: declining to answer when the retrieved passages hold no answer. Our "correct refusal" rate measures it.
- **LLM-as-a-judge.** L. Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", *NeurIPS 2023 Datasets and Benchmarks*, [arXiv:2306.05685](https://arxiv.org/abs/2306.05685). Strong judges agree with human preferences over 80% of the time, about as often as humans agree with each other. The paper also reports position, verbosity and self-enhancement bias. Because of the last one, our judge comes from a different model family from the one that writes the answers.

We do not install the `ragas` package. It pulls in LangChain and makes several model calls per metric per question, which the free models' daily request cap can't support. `evaluation/judge.py` gets every verdict from one call per question, worded after the RAGAS prompts. `evaluation/metrics.py` then applies the RAGAS formulas.

## The metrics

Each metric runs from 0 to 1, and higher is better. A metric is averaged only over the questions it applies to, and every chart shows that count (n). Error bars are 95% bootstrap intervals for the mean.

### Faithfulness: does the answer stick to the manual?

**Plain language:** the share of the answer's statements that the retrieved passages actually support. A low score means the answer adds facts the manual didn't give it, which is the hallucination risk.

**RAGAS:** split the response into claims, check each claim against the retrieved context, and compute supported claims ÷ all claims.

**Here:** the judge breaks the answer into short standalone statements (citation markers removed) and marks each one supported or not, using the full text of the passages the answering model was given. A refusal makes no statements, so it has no faithfulness score; refusals are counted separately.

### Answer relevancy: does the answer address the question?

**Plain language:** whether the answer responds to what was asked, rather than to a neighbouring question or with padding. It does not check correctness, which is what faithfulness is for.

**RAGAS:** an LLM writes 3 questions that the answer would answer. The score is the mean cosine similarity between their embeddings and the embedding of the real question. A noncommittal answer ("I don't know") scores 0.

**Here:** the judge writes the 3 questions and flags noncommittal answers. The embeddings come from the app's own `BAAI/bge-small-en-v1.5` model, while RAGAS defaults to an OpenAI embedding model. Absolute values therefore differ somewhat from a stock RAGAS run, and answers that are on topic typically score about 0.8 to 0.95. When the manual does answer a question but the app refuses it, the refusal scores 0, as RAGAS scores a noncommittal answer.

### Context precision: is the retrieved information relevant, and ranked first?

**Plain language:** of the passages the search handed to the model, how many are actually useful, with credit for putting the useful ones at the top. A low score means the search pulls in irrelevant material.

**RAGAS (LLM-based, with a reference):** for the chunks at ranks k = 1..K, let v_k = 1 if chunk k is useful for reaching the reference answer. Then

  context precision = Σ_k (precision@k × v_k) ÷ (number of useful chunks in the top K), where precision@k = useful chunks in the top k ÷ k.

**Here:** the judge marks each passage the model saw as useful or not for the reference answer. This covers the top 5 reranked chunks plus the chunk that follows each of the top 2, with consecutive chunks merged, as the app does. The passages are then put back in reranker-score order, because the model reads them in document order. The metric needs a reference answer, so it is scored on answerable questions only.

### Context recall: did the search find everything needed?

**Plain language:** the share of the facts in the correct answer that appear in the retrieved passages. A low score means important information was missed before the model even started writing.

**RAGAS (LLM-based):** split the reference answer into claims and compute claims attributable to the retrieved context ÷ all claims.

**Here:** the judge breaks each reference answer (see the test set below) into statements and marks each one found or not found in the passages. Answerable questions only.

### Page metrics: the same questions without an LLM

Each answerable question has the PDF page or pages known to hold its answer. The cross-check compares those pages with the search results directly, with no model involved.

- **Hit@5:** a chunk from a gold page is in the top 5.
- **Reciprocal rank:** 1 ÷ the rank of the first gold-page chunk (0 if none is in the top 5). The mean is the MRR.
- **Page precision:** the context precision formula above, with v_k = "chunk k is from a gold page". This is the non-LLM counterpart of context precision. RAGAS's own non-LLM variant compares passages by string distance; we compare pages.
- **Page recall:** gold pages the model was shown ÷ gold pages. When several pages each hold the whole answer on their own (a key phrase printed on more than one page), any one of them counts in full.

### Answer time

**Plain language:** how long one question takes from arrival to the checked answer.

**Here:** the app's own `StepTimer` times every step (`embed`, `search`, `rerank`, `llm`, `citations`, `retry`, `suggest`, as in `/api/ask`'s `timing_ms`), along with the total. The run is local: retrieval runs on this machine's CPU, as on Vercel, and the model call goes to whichever endpoint answered. The charts show the distribution of totals (median and 90th percentile) and the median of each step.

### Two extra checks on the same answers

- **Correct refusal (negative rejection):** for questions the manual doesn't answer, the share the app refuses.
- **Table answers:** for the 13 table questions, the share whose answer contains the expected value. The accept/reject strings are those in `eval/table_questions.json`, graded by `eval/run_eval.grade`.

## The test set

`evaluation/testset.json` is built by `python -m evaluation.build_testset`, and every item records where it came from (`origin`):

| Source | Questions | Gold pages | Reference answer |
|---|---|---|---|
| `eval/retrieval_pages.json` | 70 (B, A, X, T, U) | listed pages, or the pages of the chunks that hold the case's `key` phrase | B, A, X: the hand-checked "Expected" answers in `hosted/RESULTS-local.md`; T, U: the sentence of the manual holding the key phrase |
| `eval/table_questions.json` | 13 table questions + Q9 (not in the documents) | listed pages | the first sentence of the case's note (the table value) |
| `hosted/RESULTS-local.md` | N1-N4 (not in the asked division's documents) | none | none |
| `ncdot-agentic-ai/evaluation/tmp_manual_test_set_v1.md` | 15 items: 13 are questions already in the set (their origin is added) and 2 are new (TMP9, TMP12) | TMP9 and TMP12: chapter pages mapped to PDF pages and checked against the index text | the expected answer, where no hand-checked one exists |
| `ncdot-agentic-ai/evaluation/demo_questions_v1.md` | 12, all already in the set | | origin only |

That gives 90 questions: 85 the manuals answer (52 Work Zone, 33 Utilities) and 5 they don't. The reference answers have page and section locators removed ("; UAM 3.6.4.1, PDF p. 126"), because a page number is not a statement a passage can support. Locators left in would lower context recall.

## How the run works

`python -m evaluation.run_ragas` (see its docstring for the flags) does four things:

1. **Retrieval (no LLM, always):** ranks every question's passages and computes the page metrics.
2. **Answer:** runs the app's own `Answerer`, with the same prompt, citation check, retry and refusal as `/api/ask`, under the same 55 s budget.
3. **Judge:** makes one call per answer and returns every verdict above as JSON. An unreadable or incomplete reply is asked again once. A refused question that no document answers needs no verdict.
4. **Report:** writes `evaluation/results/scores.json` and the charts in `evaluation/charts/`.

By default the answers come from the app's own settings (`OPENROUTER_MODEL` and `OPENROUTER_FALLBACK_MODELS`, free models only). The judge is `google/gemma-4-31b-it:free` with OpenRouter falling back to `dots-studio/dots-3-note-preview:free`. Both come from a different family from the app's Nemotron answers, and the request caps the price at zero, so no paid model can be routed to. Each verdict records the model that actually gave it.

Answers and verdicts are cached in `evaluation/results/cache.jsonl`, so a run that stops resumes where it left off. An answer is keyed by question and answering models. A verdict is keyed by question, the exact answer and passages it judged, the question and reference answer it was judged against, and the judge models, so editing a reference in the test set asks the judge again. A run stops at the free daily cap (`DAILY_LIMIT`), waits out per-minute limits (`BUSY`), and never asks a cached question again. The answering model and the judge can be switched by flag. A switch goes into the cache key, so results from different models don't mix. For example, to rerun the judge on the OpenAI API, set `JUDGE_API_KEY` and use `--judge-base-url https://api.openai.com/v1 --judge-models gpt-4o-mini`. `JUDGE_API_KEY` is used only for endpoints other than OpenRouter, and OpenRouter always gets the app's `OPENROUTER_API_KEY`. `--fallback-judge-base-url`/`--fallback-judge-models` add a second judge on another endpoint. It scores only what the first judge couldn't, for example after the first one's daily cap, and the report names the judge of every question.
