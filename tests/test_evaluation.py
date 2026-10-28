"""Tests for the RAG evaluation (evaluation/): the test set converter, the metrics and the judge's parsing.

No models and no network: the judge client runs against an httpx mock transport.
"""

import asyncio
import json

import httpx
import pytest

from evaluation import ROOT, build_testset as bt, metrics as m
from evaluation.judge import ChatClient, JudgeError, judge_messages, parse_verdicts
from evaluation.run_ragas import Cache, answer_hash, config_label, reference_hash, score_question

from divrag.llm import BUSY, DAILY_LIMIT, TOO_LONG, LLMError  # noqa: E402 (hosted/ is on sys.path via evaluation)


# --- test set converter -------------------------------------------------------

@pytest.mark.parametrize("raw, clean", [
    ("5 ft undivided / 10 ft divided; UAM 3.6.4.1, PDF p. 126", "5 ft undivided / 10 ft divided."),
    ("3 feet; Table 3-1, p. 101", "3 feet."),
    ("11 ft lanes + 2 ft shoulder or 2 ft offset to positive protection; TMP 3.3 (p. 22)",
     "11 ft lanes + 2 ft shoulder or 2 ft offset to positive protection."),
    ("10 ft (deeper needs State Utilities Manager approval); 95% of standard density, AASHTO T-99, 6-in layers; 3.6.9.1, p. 132",
     "10 ft (deeper needs State Utilities Manager approval); 95% of standard density, AASHTO T-99, 6-in layers."),
    ("No: water-filled barrier is for 45 mph or less; TMP 5.4.3 (p. 34), 5.8.9 (p. 49)",
     "No: water-filled barrier is for 45 mph or less."),
    ("Portable-device speed reduction: up to 30 days. (Ch 8, 8.2, p.2)", "Portable-device speed reduction: up to 30 days."),
    ("16:1 anchored, 12:1 unanchored.", "16:1 anchored, 12:1 unanchored."),
])
def test_clean_reference_drops_locators_but_keeps_facts(raw, clean):
    assert bt.clean_reference(raw) == clean


def test_first_sentence_keeps_decimals_and_drops_commentary():
    note = "Table 3-2 (p.59): radius 1640 ft row, 60 mph column = 1.3. The PDF text layer renders '12' as '1 2'."
    assert bt.first_sentence(note) == "Table 3-2 (p.59): radius 1640 ft row, 60 mph column = 1.3."


def test_parse_results_local_splits_expected_answers_and_negatives():
    markdown = (
        "| # | Question | Answer | Cited | Expected | Correct? | Time |\n|---|---|---|---|---|---|---|\n"
        "| B4 | What is the cover? | 3 feet [1] | [1] p. 101 | 3 feet; Table 3-1, p. 101 | Yes | 2.6 s |\n"
        "| N1 | What is the rate? | I couldn't find an answer | none | Not in the TMP manual | Yes | 2.6 s |\n"
    )
    expected, negatives = bt.parse_results_local(markdown)
    assert expected["B4"]["expected"] == "3 feet; Table 3-1, p. 101"
    assert [n["id"] for n in negatives] == ["N1"]


def test_parse_tmp_and_demo():
    tmp = bt.parse_tmp("# Title\n\n1. Intermediate-term: up to 3 days. (Ch 2, 2.2, p.1)\n14. Negative: not in the manual.\n")
    assert tmp == {1: "Intermediate-term: up to 3 days. (Ch 2, 2.2, p.1)", 14: "Negative: not in the manual."}
    demo = bt.parse_demo(
        "| # | Question | Expected answer | Page |\n|---|---|---|---|\n| 1 | How long? | Up to 30 days | 75 |\n"
        "| # | I am in | Ask | Question | Expected answer | Page |\n|---|---|---|---|---|---|\n"
        "| 9 | Work Zone | Utilities | At what distance? | 5 ft | 126 |\n## Part 2\n| 1 | ignored? | x | y |\n")
    assert demo == {1: {"question": "How long?", "expected": "Up to 30 days"},
                    9: {"question": "At what distance?", "expected": "5 ft"}}


def test_key_pages_are_every_page_holding_the_key_in_that_division():
    chunks = [
        {"division": "wztc", "page": 80, "text": "Intro. In 70 MPH speed zones, a maximum 15  MPH\nreduction may be used. Next."},
        {"division": "wztc", "page": 85, "text": "Again: in 70 mph speed zones, a maximum 15 MPH reduction may be used."},
        {"division": "utilities", "page": 3, "text": "a maximum 15 MPH reduction"},
    ]
    pages, sentence = bt.key_pages_and_sentence(chunks, "wztc", "a maximum 15 mph reduction")
    assert pages == [80, 85]
    assert sentence == "In 70 MPH speed zones, a maximum 15 MPH reduction may be used."
    with pytest.raises(ValueError):
        bt.key_pages_and_sentence(chunks, "wztc", "not there")


def test_committed_testset_is_well_formed():
    items = json.loads((ROOT / "evaluation" / "testset.json").read_text(encoding="utf-8"))["items"]
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    for item in items:
        assert item["origin"] and item["question"] and item["target"]
        if item["answerable"]:
            assert item["pages"] and item["reference"], item["id"]
            assert item["pages_mode"] in ("all", "any")
        else:
            assert not item["pages"] and item["reference"] is None
    # The 83 known-page questions are all in, plus the negatives and the two TMP items.
    assert sum(1 for i in items if i["group"] in ("known-page", "table")) == 83
    assert {"Q9", "N1", "N2", "N3", "N4"} <= {i["id"] for i in items if not i["answerable"]}


# --- metrics --------------------------------------------------------------------

def test_context_precision_follows_the_ragas_formula():
    assert m.context_precision([True, True, False]) == 1.0
    assert m.context_precision([False, True]) == pytest.approx(0.5)  # (1/2) / 1
    assert m.context_precision([True, False, True]) == pytest.approx((1 + 2 / 3) / 2)
    assert m.context_precision([False, False]) == 0.0
    assert m.context_precision([]) is None


def test_faithfulness_and_recall_are_shares_and_undefined_when_empty():
    assert m.faithfulness([True, True, False, True]) == 0.75
    assert m.faithfulness([]) is None
    assert m.context_recall([True, False]) == 0.5


def test_answer_relevancy_is_mean_cosine_and_zero_when_noncommittal():
    q = [1.0, 0.0]
    assert m.answer_relevancy(q, [[1.0, 0.0], [0.0, 1.0]], noncommittal=False) == pytest.approx(0.5)
    assert m.answer_relevancy(q, [[1.0, 0.0]], noncommittal=True) == 0.0
    assert m.answer_relevancy(q, [], noncommittal=False) is None


def test_page_metrics_all_and_any():
    page = m.page_metrics([12, 30, 126, 12, 5], shown_pages=[5, 12, 13, 30, 126], gold=[126, 127])
    assert page == {"hit": 1.0, "rr": pytest.approx(1 / 3), "precision": pytest.approx(1 / 3), "recall": 0.5}
    alternatives = m.page_metrics([80, 1], shown_pages=[1, 80], gold=[80, 85], mode="any")
    assert alternatives["recall"] == 1.0 and alternatives["rr"] == 1.0
    miss = m.page_metrics([1, 2], shown_pages=[1, 2, 3], gold=[9])
    assert miss == {"hit": 0.0, "rr": 0.0, "precision": 0.0, "recall": 0.0}
    assert m.page_metrics([1], [1], gold=[])["hit"] is None


def test_bootstrap_interval_brackets_the_mean_and_is_reproducible():
    values = [0, 1, 1, 1, 0, 1, 1, 1, 1, 0]
    low, high = m.bootstrap_ci(values)
    assert low <= m.mean(values) <= high
    assert m.bootstrap_ci(values) == [low, high]
    assert m.bootstrap_ci([1.0]) is None


# --- judge ------------------------------------------------------------------------

VERDICTS = {
    "answer_statements": [{"statement": "Cover is 3 feet.", "supported": True},
                          {"statement": "It is blue.", "supported": "no"}],
    "generated_questions": ["What is the cover?", "How deep?", ""],
    "noncommittal": False,
    "passage_verdicts": [{"passage": 2, "useful": True}, {"passage": 9, "useful": True}],
    "reference_statements": [{"statement": "3 feet", "attributed": "yes"}],
}


def test_parse_verdicts_reads_fenced_json_and_fills_missing_passages():
    parsed = parse_verdicts("```json\n" + json.dumps(VERDICTS) + "\n```", n_passages=3)
    assert [s["supported"] for s in parsed["answer_statements"]] == [True, False]
    assert parsed["generated_questions"] == ["What is the cover?", "How deep?"]
    assert parsed["useful"] == [False, True, False]  # passage 9 doesn't exist; 1 and 3 were left out
    assert parsed["missing_passages"] == 2
    assert parsed["reference_statements"] == [{"statement": "3 feet", "attributed": True}]


@pytest.mark.parametrize("reply", ["no json here", "{not json}", json.dumps(dict(VERDICTS, passage_verdicts=[])),
                                   json.dumps(dict(VERDICTS, reference_statements=[]))])
def test_parse_verdicts_rejects_unreadable_or_incomplete_replies(reply):
    with pytest.raises(JudgeError):
        parse_verdicts(reply, n_passages=3)


def test_no_reference_means_no_reference_statements_are_needed():
    parsed = parse_verdicts(json.dumps(dict(VERDICTS, reference_statements=[])), n_passages=3, has_reference=False)
    assert parsed["reference_statements"] == []


def test_judge_messages_number_the_passages_and_mark_a_missing_reference():
    messages = judge_messages("Q?", ["first", "second"], "A [1].", None)
    assert "[1]\nfirst" in messages[1]["content"] and "[2]\nsecond" in messages[1]["content"]
    assert "no reference answer" in messages[1]["content"]


def _client(handler, **kwargs) -> ChatClient:
    return ChatClient(kwargs.pop("base_url", "https://openrouter.ai/api/v1"), "key",
                      kwargs.pop("models", ["google/gemma-4-31b-it:free"]), transport=httpx.MockTransport(handler), **kwargs)


def test_chat_client_sends_free_only_openrouter_requests():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"model": "google/gemma-4-31b-it:free",
                                         "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    completion = asyncio.run(_client(handler, json_mode=True, reasoning="low").complete([{"role": "user", "content": "hi"}]))
    assert completion.text == "{}"
    assert seen["provider"] == {"max_price": {"prompt": 0, "completion": 0}}
    assert seen["response_format"] == {"type": "json_object"} and seen["reasoning"]["effort"] == "low"
    with pytest.raises(ValueError):
        ChatClient("https://openrouter.ai/api/v1", "key", ["openai/gpt-4o"])


def test_chat_client_maps_rate_limits_like_the_hosted_app():
    def daily(request):
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded: free-models-per-day"}})

    def busy(request):
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded: try again"}})

    for handler, message in ((daily, DAILY_LIMIT), (busy, BUSY)):
        with pytest.raises(LLMError) as raised:
            asyncio.run(_client(handler).complete([{"role": "user", "content": "hi"}]))
        assert raised.value.user_message == message


def test_chat_client_reads_upstream_errors_and_cut_off_replies():
    def daily_in_200(request):
        return httpx.Response(200, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}})

    def cut_off(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"answer_"}, "finish_reason": "length"}]})

    for handler, message in ((daily_in_200, DAILY_LIMIT), (cut_off, TOO_LONG)):
        with pytest.raises(LLMError) as raised:
            asyncio.run(_client(handler).complete([{"role": "user", "content": "hi"}]))
        assert raised.value.user_message == message


def test_percentile_is_nearest_rank():
    assert m.percentile(list(range(1, 11)), 90) == 9
    assert m.percentile([4.0], 90) == 4.0
    assert m.percentile([], 90) is None


def test_chat_client_tries_the_next_model_off_openrouter():
    asked = []

    def handler(request):
        body = json.loads(request.content)
        asked.append(body["model"])
        assert "provider" not in body and "models" not in body
        if body["model"] == "first":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = _client(handler, base_url="http://localhost:11434/v1", models=["first", "second"])
    assert asyncio.run(client.complete([{"role": "user", "content": "hi"}])).model == "second"
    assert asked == ["first", "second"]


# --- scoring and the cache ---------------------------------------------------------

ITEM = {"id": "B4", "question": "What is the cover?", "target": "utilities", "group": "known-page", "answerable": True,
        "pages": [101], "reference": "3 feet."}
RETRIEVAL = {"hit": 1.0, "rr": 1.0, "precision": 1.0, "recall": 1.0, "ranked_pages": [101], "retrieval_ms": 200}


def _record(refused=False):
    return {"kind": "answer", "id": "B4", "answer_config": "x", "timing_ms": {"total": 2500, "llm": 2000},
            "answer": {"answer": "I couldn't find it." if refused else "3 feet [1].", "refused": refused,
                       "uncited": False, "model": "m", "sources": [] if refused else [{"page": 101, "page_end": None}]},
            "passages": [{"n": 1, "score": -1.0, "text": "other"}, {"n": 2, "score": 3.0, "text": "3 feet of cover"}]}


def test_score_question_orders_passages_by_rank_for_precision():
    verdict = {"model": "judge", "verdicts": {
        "answer_statements": [{"statement": "Cover is 3 feet", "supported": True}],
        "generated_questions": ["q"], "noncommittal": False, "useful": [False, True],
        "reference_statements": [{"statement": "3 feet", "attributed": True}]}}
    row = score_question(ITEM, RETRIEVAL, _record(), verdict, embed=lambda texts: [[1.0, 0.0]] * len(texts))
    assert row["outcome"] == "answered" and row["total_ms"] == 2500
    # Passage 2 has the higher reranker score, so the useful passage ranks first.
    assert row["context_precision"] == 1.0
    assert row["faithfulness"] == 1.0 and row["context_recall"] == 1.0 and row["answer_relevancy"] == pytest.approx(1.0)


def test_a_refused_answerable_question_scores_zero_relevancy_and_no_faithfulness():
    verdict = {"model": "judge", "verdicts": {"answer_statements": [], "generated_questions": [], "noncommittal": True,
                                              "useful": [False, True], "reference_statements": [{"statement": "3 feet", "attributed": True}]}}
    row = score_question(ITEM, RETRIEVAL, _record(refused=True), verdict)
    assert row["outcome"] == "refused"
    assert row["faithfulness"] is None and row["answer_relevancy"] == 0.0 and row["context_recall"] == 1.0


def test_a_refused_negative_is_a_correct_refusal():
    negative = dict(ITEM, answerable=False, pages=[], reference=None, group="negative")
    row = score_question(negative, {}, _record(refused=True), None)
    assert row["correct_refusal"] == 1.0 and row["answer_relevancy"] is None


def test_cache_keeps_the_latest_record_and_ties_verdicts_to_the_answer(tmp_path):
    cache = Cache(tmp_path / "cache.jsonl")
    record = _record()
    cache.add(record)
    cache.add({"kind": "judge", "id": "B4", "answer_config": "x", "answer_hash": answer_hash(record),
               "reference_hash": reference_hash(ITEM), "judge_config": "j", "verdicts": {}})
    reloaded = Cache(tmp_path / "cache.jsonl")
    assert reloaded.answer("B4", "x")["answer"]["answer"] == "3 feet [1]."
    assert reloaded.verdict(ITEM, "x", record, "j") is not None
    changed = _record(refused=True)
    assert reloaded.verdict(ITEM, "x", changed, "j") is None  # a different answer needs a new verdict
    edited = dict(ITEM, reference="Something else.")
    assert reloaded.verdict(edited, "x", record, "j") is None  # so does an edited reference answer
    assert config_label("https://openrouter.ai/api/v1", ["a:free", "b:free"]) == "openrouter.ai:a:free+b:free"
