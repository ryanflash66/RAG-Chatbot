"""Tests for the hosted demo's answers: citations, refusals, prompt, settings and the OpenRouter client."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag import answer as answer_module  # noqa: E402
from divrag import llm as llm_module  # noqa: E402
from divrag.answer import (  # noqa: E402
    HISTORY_ANSWER_CHARS, HISTORY_QUESTION_CHARS, HISTORY_TURNS, NOT_FOUND, SUGGEST_CANDIDATES, Answerer, LiveSteps,
    _VisibleText, attach_sources, build_messages, cited_numbers, live_step_labels,
)
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import (  # noqa: E402
    BUSY, DAILY_LIMIT, MISCONFIGURED, TOO_LONG, UNAVAILABLE, Completion, LLMError, OpenRouterClient,
)
from divrag.timing import StepTimer  # noqa: E402

UAM = "20220713 NCDOT UAM Ver 2-0.pdf"
TMP = "TMP Design Manual (Combined, No Links).pdf"
TODS = "TODS Manual - September 2024.pdf"


def _hit(page, text="text", source=UAM, division="utilities", section=None, score=1.0):
    return Hit(score, {"text": text, "source": source, "page": page, "section": section, "division": division})


def test_citations_are_renumbered_in_order_with_document_page_and_url():
    hits = [_hit(126, section="3.6.4.1 Lane and Road Closures"), _hit(127), _hit(101)]

    text, sources = attach_sources("Closure within 5 feet [3]. Detours are reimbursed [1, 2].", hits)

    assert text == "Closure within 5 feet [1]. Detours are reimbursed [2][3]."
    assert [(s.n, s.page) for s in sources] == [(1, 101), (2, 126), (3, 127)]
    assert sources[1].title.startswith("Utilities Accommodation Manual")
    assert sources[1].section == "3.6.4.1 Lane and Road Closures"
    assert sources[1].url.startswith("https://connect.ncdot.gov/") and sources[1].url.endswith("#page=126")
    assert sources[1].division == "utilities"


def test_passages_from_the_same_page_share_one_source_and_bad_markers_are_dropped():
    hits = [_hit(18, "a"), _hit(18, "b"), _hit(40)]

    text, sources = attach_sources("Three days [2]. Also [1][2]. Not real [9]. 【3】", hits)

    assert [s.page for s in sources] == [18, 40]
    assert text == "Three days [1]. Also [1]. Not real. [2]"


def _merged(*parts):
    chunks = [{"text": text, "source": UAM, "page": page, "section": section, "division": "utilities"}
              for text, page, section in parts]
    first = chunks[0]
    return dict(first, text="\n\n".join(c["text"] for c in chunks), page_end=chunks[-1]["page"],
                section="; ".join(c["section"] for c in chunks), parts=chunks)


def test_a_merged_passage_is_cited_by_the_pages_the_answer_drew_on():
    passage = _merged(
        ("Barrier types: concrete barrier weighs 3,900 lbs.", 32, "5.4 Types"),
        ("The NC-PCB is 10 ft long, 24 in wide at the base and 32 in high.", 33, "5.4.1 NC-PCB"),
        ("Water-filled barrier is for 45 mph or less.", 34, "5.4.3 Water-Filled"),
    )

    text, sources = attach_sources("The NC-PCB is 10 ft long and 32 in high [1].", [Hit(1.0, passage)])

    (source,) = sources
    assert (source.page, source.page_end) == (33, None)
    assert source.section == "5.4.1 NC-PCB"
    assert source.url.endswith("#page=33")


def test_a_rule_spanning_two_pages_is_cited_with_both():
    passage = _merged(
        ("D) Drop-offs greater than 12 inches: 1. traffic barrier 2. wedge slope", 16, "2.4"),
        ("3. Provide a lateral distance of 6 feet; more than 3 days use traffic barrier", 17, "2.4"),
        ("Chapter 3 lane widths are 11 feet", 18, "3.3"),
    )

    _, sources = attach_sources(
        "Use traffic barrier or a wedge slope, or shift traffic 6 feet; for more than 3 days use traffic barrier [1].",
        [Hit(1.0, passage)],
    )

    assert (sources[0].page, sources[0].page_end) == (16, 17)


def test_cited_numbers_handles_ranges_and_lists():
    assert cited_numbers("x [2-3] y [1; 3] z [5]", 4) == [2, 3, 1]


def test_prompt_frames_the_asker_but_contains_only_the_targets_passages():
    hits = [_hit(126, "Lane closure within 5 feet.")]
    system, user = build_messages("When is a lane closure needed?", BY_ID["wztc"], BY_ID["utilities"], hits)

    assert "Utilities" in system["content"] and "Work Zone Traffic Control" in system["content"]
    assert NOT_FOUND in system["content"]
    assert "[1] (Utilities Accommodation Manual" in user["content"] and "PDF page 126" in user["content"]
    assert "When is a lane closure needed?" in user["content"]


BRIDGE = "When must portable concrete barrier on a bridge deck be anchored?"
FOLLOW_UP = "What if it is more than 6 feet from the edge?"


def _turn(question, answer="An answer [1]."):
    return {"question": question, "answer": answer}


def test_search_query_is_the_question_alone_without_history():
    assert Answerer(None, None).search_query(BRIDGE) == BRIDGE
    assert Answerer(None, None).search_query(BRIDGE, []) == BRIDGE


def test_a_follow_up_is_searched_with_only_the_previous_question_before_it():
    history = [_turn("Who pays for a detour?"), _turn(BRIDGE)]

    query = Answerer(None, None).search_query(FOLLOW_UP, history)

    assert query == f"{BRIDGE} {FOLLOW_UP}"
    assert "detour" not in query  # older turns don't steer the search


def test_a_long_previous_question_is_clipped_so_the_follow_up_still_gets_read():
    query = Answerer(None, None).search_query(FOLLOW_UP, [_turn("barrier " * 400)])
    assert query.endswith(FOLLOW_UP) and len(query) < 600


def test_a_long_previous_question_without_spaces_is_cut_at_the_limit_not_dropped():
    # A pasted URL or part number has no word boundary to cut at; the prefix is kept, cut hard.
    query = Answerer(None, None).search_query(FOLLOW_UP, [_turn("x" * 5000)])
    assert query == "x" * HISTORY_QUESTION_CHARS + " … " + FOLLOW_UP


def test_a_long_earlier_answer_without_spaces_is_cut_at_the_limit_not_dropped():
    _, user = build_messages(FOLLOW_UP, BY_ID["wztc"], BY_ID["wztc"], [_hit(40, source=TMP, division="wztc")],
                             [_turn(BRIDGE, "y" * 3000)])
    assert "Earlier answer: " + "y" * HISTORY_ANSWER_CHARS + " …\n" in user["content"]


def test_prompt_shows_the_earlier_turns_before_the_passages_with_a_passages_only_rule():
    hits = [_hit(40, "Anchor the barrier when it is within 6 feet of the deck edge.", source=TMP, division="wztc")]
    history = [_turn(BRIDGE, "When it is within 6 feet of the deck edge [1]. It must be pinned [2][3].")]

    system, user = build_messages(FOLLOW_UP, BY_ID["wztc"], BY_ID["wztc"], hits, history)

    content = user["content"]
    assert content.index("Earlier conversation") < content.index("Earlier question: " + BRIDGE) < content.index("[1] (")
    assert "Earlier answer: When it is within 6 feet of the deck edge. It must be pinned." in content
    assert content.rstrip().endswith("Question: " + FOLLOW_UP)
    # The old answer's [n] numbered other passages; only the new passages are numbered.
    assert content.count("[1]") == 1 and "[2]" not in content
    # Every existing rule stays, plus one saying the earlier turns are not a source.
    assert "1. Use only the numbered passages." in system["content"]
    assert f"reply with exactly {NOT_FOUND} and nothing else" in system["content"]
    assert "8. The earlier conversation" in system["content"]
    assert "It is not a source: take every fact from the numbered passages" in system["content"]
    assert f"reply with exactly {NOT_FOUND}, even if the earlier conversation did" in system["content"]


def test_a_question_carried_over_from_another_division_is_shown_without_an_answer():
    # "Ask Utilities instead" on a refused follow-up sends the previous question with no answer.
    hits = [_hit(126, "Lane closure within 5 feet.")]

    _, user = build_messages(FOLLOW_UP, BY_ID["wztc"], BY_ID["utilities"], hits, [_turn(BRIDGE, "")])

    assert "Earlier question: " + BRIDGE in user["content"]
    assert "Earlier answer" not in user["content"]
    assert Answerer(None, None).search_query(FOLLOW_UP, [_turn(BRIDGE, "")]) == f"{BRIDGE} {FOLLOW_UP}"


def test_a_first_question_gets_the_prompt_without_any_history_part():
    hits = [_hit(126, "Lane closure within 5 feet.")]

    system, user = build_messages("When is a lane closure needed?", BY_ID["wztc"], BY_ID["utilities"], hits, [])

    assert "earlier conversation" not in system["content"].lower()
    assert user["content"].startswith("Passages from the Utilities division's documents:")


def test_only_the_last_three_turns_reach_the_prompt_and_long_answers_are_clipped():
    history = [_turn(f"Question number {n}?", f"Answer number {n} [1].") for n in range(1, 7)]
    history[-1]["answer"] = "word " * 1000

    _, user = build_messages(FOLLOW_UP, BY_ID["wztc"], BY_ID["wztc"], [_hit(40, source=TMP, division="wztc")], history)

    content = user["content"]
    assert HISTORY_TURNS == 3
    assert [n for n in range(1, 7) if f"Question number {n}?" in content] == [4, 5, 6]
    last_answer = content.split("Earlier answer: ")[-1].split("\n\n")[0]
    assert len(last_answer) <= HISTORY_ANSWER_CHARS + 2 and last_answer.endswith(" …")


class _FakeLLM:
    """Replies with `text`; a list of texts is replayed one per call (the last repeats)."""

    def __init__(self, text):
        self.texts = [text] if isinstance(text, str) else list(text)
        self.calls = []
        self.models_used = []

    def retry_models(self, used):
        return ["test/second:free"]

    async def complete(self, messages, models=None):
        self.calls.append(messages)
        self.models_used.append(models)
        text = self.texts[min(len(self.calls), len(self.texts)) - 1]
        if isinstance(text, Exception):
            raise text
        return Completion(text, "test/model:free" if models is None else models[0])

    def complete_stream(self, messages, models=None):
        self.calls.append(messages)
        self.models_used.append(models)
        return _FakeStream(self.texts[min(len(self.calls), len(self.texts)) - 1],
                           "test/model:free" if models is None else models[0])


class _FakeStream:
    """A streamed reply in pieces of four characters; an exception reply is raised while iterating."""

    def __init__(self, reply, model):
        self.reply, self.model, self.text = reply, model, ""

    def __aiter__(self):
        return self._pieces()

    async def _pieces(self):
        if isinstance(self.reply, Exception):
            raise self.reply
        for start in range(0, len(self.reply), 4):
            yield self.reply[start:start + 4]
        self.text = self.reply.strip()


class _FakeRetriever:
    """Returns a fixed best score per division; records which divisions were searched."""

    def __init__(self, scores, reranker=True):
        self.scores = scores
        self.reranker = object() if reranker else None
        self.searched = []
        self.candidates = []
        self.questions = []

    def retrieve(self, question, division, k=5, timer=None, candidates=None, sources=None):
        self.searched.append(division)
        self.candidates.append(candidates)
        self.questions.append(question)
        source = {"wztc": TMP, "tmsd": TODS}.get(division, UAM)
        # A division a test gives no score to (tmsd, unless named) has nothing relevant.
        return [_hit(10, source=source, division=division, score=self.scores.get(division, -9.0))]

    def with_following(self, hits, top=2):
        return hits

    def as_passages(self, hits):
        return hits


def _answer(llm_text, scores=None, target="utilities"):
    retriever = _FakeRetriever(scores or {"wztc": -9.0, "utilities": -9.0})
    answerer = Answerer(retriever, _FakeLLM(llm_text))
    hits = retriever.retrieve("q", target)
    return asyncio.run(answerer.answer("q", BY_ID["wztc"], BY_ID[target], hits)), retriever


def _ask_with_retry(replies, score, seconds_left=None, reranker=True, **options):
    """Answer a Utilities question whose best passage scores `score`; returns (result, llm)."""
    retriever = _FakeRetriever({"wztc": -9.0, "utilities": score}, reranker=reranker)
    llm = _FakeLLM(replies)
    answerer = Answerer(retriever, llm, **options)
    hits = retriever.retrieve("q", "utilities")
    deadline = None if seconds_left is None else time.monotonic() + seconds_left
    return asyncio.run(answerer.answer("q", BY_ID["utilities"], BY_ID["utilities"], hits, deadline)), llm


def test_answer_with_citations_is_not_a_refusal():
    result, _ = _answer("Three feet [1].")
    assert not result.refused
    assert result.answer == "Three feet [1]."
    assert len(result.sources) == 1 and result.sources[0].url.endswith("#page=10")


def test_not_in_documents_reply_is_a_refusal_with_no_sources():
    result, retriever = _answer(NOT_FOUND)

    assert result.refused
    assert result.sources == []
    assert "Utilities documents" in result.answer and "Utilities Accommodation Manual" in result.answer
    assert result.suggest == []  # the other division's best passage scored too low


def test_answer_without_any_citation_is_kept_and_flagged_uncited():
    # DAR-629: shown with a "No source cited" flag instead of being turned into a refusal.
    result, retriever = _answer("The rate is $50 per hour.")

    assert not result.refused and result.uncited
    assert result.answer == "The rate is $50 per hour." and result.sources == []
    assert result.as_dict()["uncited"] is True
    assert retriever.searched == ["utilities"]  # not a refusal, so no search for another division


def test_a_cited_answer_is_not_flagged_uncited():
    result, _ = _answer("Three feet [1].")
    assert result.as_dict()["uncited"] is False


def test_a_refusal_worded_around_the_marker_is_still_a_refusal():
    result, _ = _answer(f"I'm sorry, {NOT_FOUND}.")
    assert result.refused and not result.uncited and result.sources == []


def test_the_marker_inside_a_cited_answer_is_cut_out():
    result, _ = _answer(f"Three feet [1]. {NOT_FOUND}")
    assert not result.refused and result.answer == "Three feet [1]."


def test_refusal_suggests_the_other_division_when_its_documents_look_relevant():
    result, retriever = _answer(NOT_FOUND, scores={"wztc": 3.2, "utilities": -9.0})

    assert result.refused
    assert result.suggest == ["wztc"]
    assert retriever.candidates[-1] == SUGGEST_CANDIDATES  # a smaller rerank than the question's own
    assert "try asking Work Zone Traffic Control" in result.answer
    assert result.as_dict()["suggest"] == [{"id": "wztc", "name": "Work Zone Traffic Control"}]


def test_refusal_suggests_every_other_division_whose_documents_look_relevant():
    result, retriever = _answer(NOT_FOUND, scores={"wztc": 3.2, "utilities": -9.0, "tmsd": 2.9})

    assert result.suggest == ["wztc", "tmsd"]
    assert retriever.searched[1:] == ["wztc", "tmsd"]  # every division but the one asked
    assert result.answer.endswith(
        "try asking one of them instead: Work Zone Traffic Control; Transportation Mobility and Safety.")


def test_suggestions_stop_when_the_request_is_nearly_out_of_time(monkeypatch):
    retriever = _FakeRetriever({"wztc": 3.2, "tmsd": 2.9})
    answerer = Answerer(retriever, _FakeLLM(NOT_FOUND))
    now = [100.0]
    monkeypatch.setattr(answer_module, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def retrieve(question, division, **kwargs):
        now[0] += 2.0  # each division's check takes 2 s
        return _FakeRetriever.retrieve(retriever, question, division, **kwargs)
    retriever.retrieve = retrieve

    # 4.5 s left: wztc is checked; 2.5 s are left after it, under SUGGEST_MIN_SECONDS, so tmsd is skipped.
    assert answerer.suggest_divisions("q", BY_ID["utilities"], deadline=104.5) == ["wztc"]
    assert retriever.searched == ["wztc"]
    assert answerer.suggest_divisions("q", BY_ID["utilities"], deadline=None) == ["wztc", "tmsd"]


@pytest.mark.parametrize("first", [NOT_FOUND, f"Sorry, {NOT_FOUND}."])
def test_refusal_despite_strong_retrieval_is_retried_once_with_the_next_model(first):
    result, llm = _ask_with_retry([first, "Three feet [1]."], score=3.5, seconds_left=40)

    assert not result.refused and result.retried
    assert result.answer == "Three feet [1]." and len(result.sources) == 1
    assert result.model == "test/second:free"
    assert llm.models_used == [None, ["test/second:free"]]
    assert llm.calls[0] == llm.calls[1]  # same prompt, different model


def test_a_follow_up_is_retrieved_answered_retried_and_suggested_with_its_history():
    retriever = _FakeRetriever({"wztc": -9.0, "utilities": 3.5})
    llm = _FakeLLM([NOT_FOUND, NOT_FOUND])
    answerer = Answerer(retriever, llm)
    history = [_turn("Who pays for a detour?"), _turn(BRIDGE, "Within 6 feet of the edge [1].")]

    hits = answerer.retrieve(FOLLOW_UP, BY_ID["utilities"], history=history)
    result = asyncio.run(answerer.answer(FOLLOW_UP, BY_ID["utilities"], BY_ID["utilities"], hits, time.monotonic() + 40,
                                         history=history))

    assert retriever.questions[0] == f"{BRIDGE} {FOLLOW_UP}"
    assert result.refused and result.retried
    assert len(llm.calls) == 2 and llm.calls[0] == llm.calls[1]  # the retry reuses the prompt, history included
    assert "Earlier question: " + BRIDGE in llm.calls[1][1]["content"]
    assert retriever.questions[1:] == [f"{BRIDGE} {FOLLOW_UP}"] * 2  # the other divisions are checked on the same topic


def test_an_uncited_answer_is_kept_not_retried():
    # Only a "not found" is retried (DAR-629); before, an uncited answer counted as one.
    result, llm = _ask_with_retry(["The rate is three feet.", "Three feet [1]."], score=3.5, seconds_left=40)

    assert not result.refused and not result.retried and result.uncited
    assert result.answer == "The rate is three feet."
    assert len(llm.calls) == 1


def test_an_uncited_answer_from_the_retry_does_not_replace_the_refusal():
    # One model found nothing and the next answers without a citation: most likely outside knowledge.
    result, _ = _ask_with_retry([NOT_FOUND, "Three feet."], score=3.5, seconds_left=40)

    assert result.refused and result.retried and not result.uncited
    assert "Utilities documents" in result.answer


class _SlowLLM(_FakeLLM):
    async def complete(self, messages, models=None):
        await asyncio.sleep(0.03)
        return await super().complete(messages, models)


def test_answer_times_the_model_call_citations_and_retry_and_names_both_models():
    timer = StepTimer()
    retriever = _FakeRetriever({"wztc": -9.0, "utilities": 3.5})
    answerer = Answerer(retriever, _SlowLLM([NOT_FOUND, "Three feet [1]."]))
    hits = retriever.retrieve("q", "utilities")

    result = asyncio.run(answerer.answer("q", BY_ID["utilities"], BY_ID["utilities"], hits, time.monotonic() + 40, timer))

    ms = timer.as_ms()
    assert ms["llm"] >= 25 and ms["retry"] >= 25  # one slow call each
    assert ms["suggest"] == 0  # the retry answered, so no refusal to suggest for
    assert (result.first_model, result.model) == ("test/model:free", "test/second:free")
    assert result.as_dict()["first_model"] == "test/model:free" and result.as_dict()["retried"] is True


def test_refusal_times_the_search_of_the_other_division_as_suggest():
    class _SlowRetriever(_FakeRetriever):
        def retrieve(self, question, division, k=5, timer=None, candidates=None, sources=None):
            time.sleep(0.03)
            return super().retrieve(question, division, k, timer, candidates, sources)

    timer = StepTimer()
    retriever = _SlowRetriever({"wztc": -9.0, "utilities": 0.5})
    answerer = Answerer(retriever, _FakeLLM(NOT_FOUND))
    hits = retriever.retrieve("q", "utilities")

    result = asyncio.run(answerer.answer("q", BY_ID["wztc"], BY_ID["utilities"], hits, None, timer))

    ms = timer.as_ms()
    assert result.refused and not result.retried
    assert ms["suggest"] >= 25 and ms["retry"] == 0
    assert ms["embed"] == 0  # the suggestion's own searches are not counted as the question's


def test_no_retry_when_retrieval_is_weak():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=0.5, seconds_left=40)

    assert result.refused and not result.retried
    assert len(llm.calls) == 1


def test_no_retry_without_a_reranker_because_scores_are_then_not_comparable():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, reranker=False)

    assert result.refused and len(llm.calls) == 1


def test_no_retry_when_too_little_of_the_time_budget_is_left():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=10)

    assert result.refused and not result.retried
    assert len(llm.calls) == 1


def test_no_retry_when_switched_off():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=40, retry_min_score=None)

    assert result.refused and len(llm.calls) == 1


def test_refusal_is_returned_when_the_retry_refuses_too():
    result, llm = _ask_with_retry([NOT_FOUND, NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=40)

    assert result.refused and result.retried and result.sources == []
    assert len(llm.calls) == 2  # retried once, not more
    assert "Utilities documents" in result.answer


def test_refusal_is_returned_when_the_retry_fails_or_runs_out_of_time():
    failed, _ = _ask_with_retry([NOT_FOUND, LLMError(BUSY, status=429)], score=3.5, seconds_left=40)
    assert failed.refused and failed.retried

    class _SlowRetry(_FakeLLM):
        async def complete(self, messages, models=None):
            if models:
                await asyncio.sleep(30)
            return await super().complete(messages, models)

    retriever = _FakeRetriever({"wztc": -9.0, "utilities": 3.5})
    answerer = Answerer(retriever, _SlowRetry(NOT_FOUND), retry_min_seconds=0.0)
    hits = retriever.retrieve("q", "utilities")
    started = time.monotonic()
    slow = asyncio.run(answerer.answer("q", BY_ID["utilities"], BY_ID["utilities"], hits, started + 1.5))
    assert slow.refused and time.monotonic() - started < 1.5  # gave up before the request deadline


def test_no_retry_when_less_than_the_retry_margin_is_left():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=0.5, retry_min_seconds=0.0)

    assert result.refused and not result.retried  # not reported as a retry that never got to call the model
    assert len(llm.calls) == 1


def test_retry_settings_have_defaults_and_can_be_changed():
    default = load_settings({})
    assert (default.retry_on_refusal, default.retry_min_score, default.retry_min_seconds) == (True, 1.0, 15.0)
    custom = load_settings({"RETRY_ON_REFUSAL": "off", "RETRY_MIN_SCORE": "2.5", "RETRY_MIN_SECONDS": "20"})
    assert (custom.retry_on_refusal, custom.retry_min_score, custom.retry_min_seconds) == (False, 2.5, 20.0)
    with pytest.raises(ValueError):
        load_settings({"RETRY_ON_REFUSAL": "maybe"})


def test_retry_models_are_the_ones_after_the_model_that_answered():
    client = OpenRouterClient("k", ["a:free", "b:free", "c:free"])
    assert client.retry_models("a:free") == ["b:free", "c:free"]
    assert client.retry_models("c:free") == ["c:free"]  # no fallback left: same model
    assert client.retry_models("unknown:free") == ["b:free", "c:free"]
    assert OpenRouterClient("k", ["a:free"]).retry_models("a:free") == ["a:free"]


def test_complete_can_override_the_model_list():
    seen = {}

    def handler(request):
        seen["models"] = json.loads(request.content)["models"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok [1]"}}]})

    asyncio.run(_client(handler).complete([], models=["e/f:free"]))
    assert seen["models"] == ["e/f:free"]


def test_settings_reject_paid_models():
    with pytest.raises(ValueError):
        load_settings({"OPENROUTER_MODEL": "openai/gpt-4o"})
    with pytest.raises(ValueError):
        load_settings({"OPENROUTER_FALLBACK_MODELS": "x/y:free, openai/gpt-4o"})
    settings = load_settings({"OPENROUTER_MODEL": "a/b:free", "OPENROUTER_FALLBACK_MODELS": "c/d:free", "RERANK": "off"})
    assert settings.models == ("a/b:free", "c/d:free")
    assert settings.rerank is False


@pytest.mark.parametrize("value", ["two", "0", "-1", "1.5"])
def test_a_bad_onnx_threads_value_stops_startup(value):
    with pytest.raises(ValueError):
        load_settings({"ONNX_THREADS": value})
    load_settings({"ONNX_THREADS": "2"})


def test_request_budget_defaults_under_vercels_limit_and_rejects_values_above_it():
    assert load_settings({}).request_budget_seconds == 55
    assert load_settings({"REQUEST_BUDGET_SECONDS": "30"}).request_budget_seconds == 30
    with pytest.raises(ValueError):
        load_settings({"REQUEST_BUDGET_SECONDS": "60"})


def _client(handler):
    return OpenRouterClient("sk-test", ["a/b:free", "c/d:free"], transport=httpx.MockTransport(handler))


def test_openrouter_client_sends_the_fallback_list_and_returns_the_answering_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"model": "c/d:free", "choices": [{"message": {"content": " Answer [1]. "}}]})

    completion = asyncio.run(_client(handler).complete([{"role": "user", "content": "hi"}]))

    assert completion == Completion("Answer [1].", "c/d:free")
    assert seen["body"]["models"] == ["a/b:free", "c/d:free"]
    assert seen["auth"] == "Bearer sk-test"


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": {"message": "rate limited"}}),
    httpx.Response(200, json={"error": {"code": 429, "message": "upstream rate limited"}}),
])
def test_rate_limits_become_a_friendly_busy_error(response):
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == BUSY
    assert caught.value.status == 429


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock."}}),
    httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded", "metadata": {"headers": {"X-RateLimit-Limit": "50"}, "reason": "free-models-per-day"}}}),
    httpx.Response(200, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}}),
])
def test_daily_free_quota_has_its_own_message(response):
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == DAILY_LIMIT
    assert caught.value.status == 429


def test_per_minute_rate_limit_stays_busy():
    response = httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded", "metadata": {"error_type": "rate_limit_exceeded"}}})
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == BUSY


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>Bad gateway</html>"),
    httpx.Response(200, json={"error": "upstream exploded"}),
    httpx.Response(200, json=["not", "an", "object"]),
    httpx.Response(200, json={"choices": "nope"}),
])
def test_malformed_upstream_responses_become_the_friendly_unavailable_error(response):
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == UNAVAILABLE
    assert caught.value.status == 503


def test_requests_cap_provider_prices_at_zero():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok [1]"}}]})

    asyncio.run(_client(handler).complete([]))
    assert seen["body"]["provider"] == {"max_price": {"prompt": 0, "completion": 0}}


def test_cut_off_answer_is_an_error_not_a_partial_answer():
    response = httpx.Response(200, json={"model": "a/b:free", "choices": [{"finish_reason": "length", "message": {"content": "We need to"}}]})
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == llm_module.TOO_LONG


def test_reasoning_is_off_unless_configured():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok [1]"}}]})

    asyncio.run(_client(handler).complete([]))
    asyncio.run(OpenRouterClient("k", ["a/b:free"], reasoning="low", transport=httpx.MockTransport(handler)).complete([]))
    assert bodies[0]["reasoning"] == {"enabled": False}
    assert bodies[1]["reasoning"]["effort"] == "low"


def test_network_failure_becomes_a_friendly_error_without_details():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(handler).complete([]))
    assert caught.value.user_message == llm_module.UNAVAILABLE
    assert "boom" not in caught.value.user_message


# Streaming (DAR-629): OpenRouter's server-sent events, the text shown while it
# is written, and the steps the page shows.

def _sse(*events):
    """An OpenRouter stream body: one "data:" event each (dicts as JSON, strings as they are)."""
    return "".join(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events)


def _chunk(text, model="c/d:free", finish=None):
    return {"model": model, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


def _read_stream(handler, pieces=None):
    """(pieces, stream) after reading a whole streamed answer; raises what the stream raises.

    Pass `pieces` to see what arrived before an error.
    """
    pieces = [] if pieces is None else pieces

    async def run():
        stream = _client(handler).complete_stream([{"role": "user", "content": "hi"}])
        async for piece in stream:
            pieces.append(piece)
        return stream

    return pieces, asyncio.run(run())


def test_complete_stream_yields_the_text_as_it_arrives_and_names_the_answering_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        body = (": OPENROUTER PROCESSING\n\n"
                + _sse(_chunk("Three"), {"model": "c/d:free", "choices": [{"delta": {"content": "", "reasoning": "hmm"}}]},
                       _chunk(" feet"), _chunk(" [1]. ", finish="stop"), {"choices": [], "usage": {"total_tokens": 9}},
                       "[DONE]", _chunk("after the end")))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    pieces, stream = _read_stream(handler)

    assert pieces == ["Three", " feet", " [1]. "]  # the reasoning is never passed on
    assert (stream.text, stream.model) == ("Three feet [1].", "c/d:free")
    assert seen["body"]["stream"] is True and seen["body"]["models"] == ["a/b:free", "c/d:free"]
    assert seen["body"]["provider"] == {"max_price": {"prompt": 0, "completion": 0}}


def test_complete_stream_reads_an_event_whose_data_spans_lines():
    body = 'data: {"model": "a/b:free",\ndata: "choices": [{"delta": {"content": "Hi [1]"}}]}\n\ndata: [DONE]\n\n'
    pieces, stream = _read_stream(lambda request: httpx.Response(200, text=body))
    assert pieces == ["Hi [1]"] and stream.model == "a/b:free"


@pytest.mark.parametrize("error,message", [
    ({"code": 502, "message": "Provider disconnected"}, UNAVAILABLE),
    ({"code": 429, "message": "Rate limit exceeded"}, BUSY),
])
def test_an_error_in_the_middle_of_the_stream_becomes_a_friendly_error(error, message):
    body = _sse(_chunk("Three"), {"error": error, "choices": [{"delta": {"content": ""}, "finish_reason": "error"}]})
    pieces = []

    with pytest.raises(LLMError) as caught:
        _read_stream(lambda request: httpx.Response(200, text=body), pieces)

    assert caught.value.user_message == message
    assert pieces == ["Three"]  # the text before the error had already been passed on


@pytest.mark.parametrize("response,message,status", [
    (httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}}), DAILY_LIMIT, 429),
    (httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded"}}), BUSY, 429),
    (httpx.Response(401, json={"error": {"message": "No auth credentials found"}}), MISCONFIGURED, 503),
    (httpx.Response(502, text="<html>Bad gateway</html>"), UNAVAILABLE, 503),
])
def test_stream_http_errors_become_the_same_friendly_errors_as_complete(response, message, status):
    with pytest.raises(LLMError) as caught:
        _read_stream(lambda request: response)
    assert (caught.value.user_message, caught.value.status) == (message, status)


@pytest.mark.parametrize("body,message", [
    (_sse(_chunk("We need to", finish="length"), "[DONE]"), TOO_LONG),
    (_sse("[DONE]"), UNAVAILABLE),
    (_sse("not json"), UNAVAILABLE),
    # Closed mid-answer, without [DONE] or a finish reason: not a complete answer.
    (_sse(_chunk("The NC-PCB is 10 ft "), _chunk("long and")), UNAVAILABLE),
])
def test_cut_off_empty_or_garbled_streams_are_errors(body, message):
    with pytest.raises(LLMError) as caught:
        _read_stream(lambda request: httpx.Response(200, text=body))
    assert caught.value.user_message == message


def test_a_dropped_stream_connection_is_a_friendly_error_without_details():
    def handler(request):
        raise httpx.ReadError("connection reset by peer")

    with pytest.raises(LLMError) as caught:
        _read_stream(handler)
    assert caught.value.user_message == UNAVAILABLE and "reset" not in caught.value.user_message


@pytest.mark.parametrize("pieces,shown", [
    (["NOT_", "IN_DOC", "UMENTS"], ""),
    (["\n NOT_IN_DOCUMENTS", ". The manual doesn't say."], ""),  # a refusal shows nothing
    (["**NOT_IN_", "DOCUMENTS**"], ""),
    (["NO", " fee applies."], "NO fee applies."),  # held while it could be the marker
    (["Three feet [1]. NOT_IN", "_DOCUMENTS"], "Three feet. "),
    (["  ", "\n", "Three"], "Three"),
    (["NOT_IN"], "NOT_IN"),  # never became the marker
])
def test_the_streamed_text_never_shows_the_not_found_marker(pieces, shown):
    visible = _VisibleText()
    assert "".join(visible.feed(piece) for piece in pieces) + visible.end() == shown


@pytest.mark.parametrize("pieces,shown", [
    (["Three feet [", "1", "] and two [2-3]."], "Three feet and two."),
    (["Shift traffic [1, ", "2]【3】 [none]."], "Shift traffic."),
    (["**Three** feet [1]"], "**Three** feet"),
    (["See [Table 4", "] on page 9."], "See [Table 4] on page 9."),  # not a citation
])
def test_the_streamed_text_leaves_out_citation_markers_until_they_are_checked(pieces, shown):
    # The prompt's [4] may become [1] after the check; the checked answer brings the citations.
    visible = _VisibleText()
    assert "".join(visible.feed(piece) for piece in pieces) + visible.end() == shown


def test_the_streamed_text_holds_back_only_what_could_start_a_marker():
    visible = _VisibleText()
    assert visible.feed("Three feet, see N") == "Three feet, see "
    assert visible.feed("ote 4 ") == "Note 4"
    assert visible.feed("[") == ""
    assert visible.feed("2] here") == " here"


def test_step_timer_tells_its_listener_when_each_step_starts_and_ends():
    heard = []
    timer = StepTimer(lambda *event: heard.append(event))

    with timer.step("embed"):
        time.sleep(0.01)
    with pytest.raises(RuntimeError):
        with timer.step("llm"):
            raise RuntimeError("model call failed")

    assert heard[0] == ("embed", "start", 0)
    assert heard[1][:2] == ("embed", "done") and heard[1][2] == timer.as_ms()["embed"] >= 5
    assert heard[2:] == [("llm", "start", 0)]  # a failed step is never reported done


def test_live_steps_count_loading_the_models_as_reading_the_question():
    sent = []
    steps = LiveSteps(live_step_labels(BY_ID["utilities"], 1234, 5), lambda event, data: sent.append((event, data)))

    for event in [("model_load", "start", 0), ("model_load", "done", 30), ("embed", "start", 0), ("embed", "done", 12),
                  ("search", "start", 0), ("search", "done", 3), ("rerank", "start", 0), ("rerank", "done", 180)]:
        steps(*event)

    assert {event for event, _ in sent} == {"step"}
    assert [(d["id"], d["status"], d["ms"]) for _, d in sent] == [
        ("read", "start", 0), ("read", "done", 42), ("search", "start", 0), ("search", "done", 3),
        ("rerank", "start", 0), ("rerank", "done", 180),
    ]
    assert sent[0][1]["label"] == "Reading your question"
    assert sent[2][1]["label"] == "Searching Utilities documents (1,234 passages)"
    assert sent[4][1]["label"] == "Picking the 5 best passages"
    assert steps.done == [{"id": "read", "label": "Reading your question", "ms": 42},
                          {"id": "search", "label": "Searching Utilities documents (1,234 passages)", "ms": 3},
                          {"id": "rerank", "label": "Picking the 5 best passages", "ms": 180}]


def test_live_steps_announce_the_expected_steps_as_pending_but_not_retry_or_suggest():
    for rerank, expected in [(True, ["read", "search", "rerank", "write", "check"]),
                             (False, ["read", "search", "write", "check"])]:
        sent = []
        steps = LiveSteps(live_step_labels(BY_ID["utilities"], 1234, 5), lambda event, data: sent.append((event, data)))
        steps.announce(rerank=rerank)
        assert [(d["id"], d["status"], d["ms"]) for _, d in sent] == [(s, "pending", 0) for s in expected]
        assert sent[1][1]["label"] == "Searching Utilities documents (1,234 passages)"
        assert steps.done == []  # announcing finishes nothing: the payload's steps are unchanged


def test_live_steps_without_a_stream_only_record_the_finished_steps():
    steps = LiveSteps(live_step_labels(BY_ID["wztc"], 10, 5))
    steps("llm", "start", 0)
    steps("llm", "done", 900)
    assert steps.done == [{"id": "write", "label": "Writing the answer", "ms": 900}]


def _stream_answer(replies, score=-9.0, seconds_left=40):
    """Stream a Utilities answer; returns (result, events, llm)."""
    retriever = _FakeRetriever({"wztc": -9.0, "utilities": score})
    llm = _FakeLLM(replies)
    events = []
    hits = retriever.retrieve("q", "utilities")
    result = asyncio.run(Answerer(retriever, llm).answer_stream(
        "q", BY_ID["wztc"], BY_ID["utilities"], hits, lambda event, data: events.append((event, data)),
        time.monotonic() + seconds_left))
    return result, events, llm


def test_a_streamed_answer_passes_the_text_on_in_pieces_and_returns_the_graded_answer():
    result, events, _ = _stream_answer("  Three feet [1].")

    assert {event for event, _ in events} == {"delta"} and len(events) > 1
    assert "".join(data["text"] for _, data in events) == "Three feet."  # the citation comes with the answer
    assert result.answer == "Three feet [1]." and len(result.sources) == 1 and not result.uncited


def test_a_streamed_refusal_shows_no_text():
    result, events, _ = _stream_answer(NOT_FOUND)
    assert events == [] and result.refused


def test_a_streamed_retry_clears_the_text_and_streams_the_next_model():
    result, events, llm = _stream_answer([NOT_FOUND, "Three feet [1]."], score=3.5)

    assert events[0] == ("replace", {"text": ""})
    assert "".join(data["text"] for _, data in events[1:]) == "Three feet."
    assert result.retried and not result.refused and result.model == "test/second:free"
    assert llm.models_used == [None, ["test/second:free"]]


def test_a_streamed_uncited_answer_is_kept_and_flagged():
    result, events, llm = _stream_answer("The rate is three feet.", score=3.5)
    assert result.uncited and not result.refused and not result.retried and len(llm.calls) == 1
    assert "".join(data["text"] for _, data in events) == "The rate is three feet."
