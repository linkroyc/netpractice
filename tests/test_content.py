import pytest

from content import ALL_QUESTIONS, MODULES, QUESTIONS_BY_MODULE
from grading import expected_answer, grade_answer, normalize_text


def test_course_has_enough_content():
    assert len(ALL_QUESTIONS) >= 40
    assert len(MODULES) == 7
    assert sum(
        1 for question in ALL_QUESTIONS
        if question["type"] in ("scenario", "troubleshoot")
    ) >= 7
    for module in MODULES:
        assert module["question_count"] > 0
        assert len(QUESTIONS_BY_MODULE[module["id"]]) == module["question_count"]


def test_all_question_types_present():
    types = {question["type"] for question in ALL_QUESTIONS}
    assert {"input", "multi", "choice", "scenario", "troubleshoot"} <= types


def test_question_ids_are_unique():
    ids = [question["id"] for question in ALL_QUESTIONS]
    assert len(ids) == len(set(ids))


def test_required_fields_and_explanations():
    for question in ALL_QUESTIONS:
        assert question["prompt"].strip()
        assert question["explanation"].strip()
        assert question["sample"].strip()
        assert question["source"].strip()
        assert question["xp"] > 0
        assert question["difficulty"] in (1, 2, 3)


@pytest.mark.parametrize("question", ALL_QUESTIONS, ids=lambda q: q["id"])
def test_content_answers_are_accepted(question):
    """Эталон из файла задания должен проходить собственную проверку."""
    result = grade_answer(question, expected_answer(question))
    assert result["correct"] is True, question["id"]
    assert result["score"] == 100


def test_choice_correct_indexes_are_valid():
    for question in ALL_QUESTIONS:
        if question["type"] == "choice":
            assert 0 <= question["correct"] < len(question["options"])


def test_written_questions_have_key_points():
    for question in ALL_QUESTIONS:
        if question["type"] in ("scenario", "troubleshoot"):
            assert len(question["keywords"]) >= 3
            assert 1 <= question["min_points"] <= len(question["keywords"])
            assert question["sample"].strip()


def _answer_texts(question):
    if question["type"] == "choice":
        return [question["options"][question["correct"]]]
    if question["type"] == "input":
        return list(question["answers"])
    if question["type"] == "multi":
        return [
            answer
            for field in question["fields"]
            for answer in field["answers"]
        ]
    return []


def test_all_tasks_have_unique_safe_hints():
    all_hints = []
    assert len(ALL_QUESTIONS) == 83
    for question in ALL_QUESTIONS:
        hints = question["hints"]
        assert 2 <= len(hints) <= 4, question["id"]
        assert all(hint.strip() for hint in hints), question["id"]
        assert len(hints) == len(set(hints)), question["id"]
        all_hints.extend(hints)

        forbidden = {
            normalize_text(value)
            for value in _answer_texts(question) + [question["sample"]]
        }
        for hint in hints:
            normalized = normalize_text(hint)
            assert normalized not in forbidden, (question["id"], hint)
            assert all(
                normalize_text(answer) not in normalized
                for answer in _answer_texts(question)
                if len(normalize_text(answer)) >= 3
            ), (question["id"], hint)

    assert len(all_hints) == len(set(all_hints))


def test_each_module_is_ordered_from_easy_to_hard():
    for module in MODULES:
        questions = QUESTIONS_BY_MODULE[module["id"]]
        difficulties = [question["difficulty"] for question in questions]
        assert difficulties == sorted(difficulties), module["id"]
        assert difficulties[-1] == 3, module["id"]
        if module["id"] != 7:
            assert difficulties.count(3) <= 2, module["id"]
