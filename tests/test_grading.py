from content import get_question
from grading import grade_answer, normalize_text


def test_mask_accepts_prefix_and_dotted_forms():
    question = get_question("m2-01")
    for value in ("255.255.255.192", "/26", "26", " 255.255.255.192 "):
        assert grade_answer(question, {"value": value})["correct"] is True, value
    assert grade_answer(question, {"value": "255.255.255.224"})["correct"] is False


def test_prefix_accepts_mask():
    question = get_question("m2-04")
    for value in ("/29", "29", "255.255.255.248"):
        assert grade_answer(question, {"value": value})["correct"] is True, value
    assert grade_answer(question, {"value": "28"})["correct"] is False


def test_integer_ignores_words():
    question = get_question("m2-08")
    assert grade_answer(question, {"value": "30"})["correct"] is True
    assert grade_answer(question, {"value": "30 адресов"})["correct"] is True
    assert grade_answer(question, {"value": "32"})["correct"] is False


def test_text_is_case_and_space_insensitive():
    question = get_question("m3-02")
    for value in ("ipconfig /all", "  IPCONFIG   /ALL ", "ipconfig/all"):
        assert grade_answer(question, {"value": value})["correct"] is True, value


def test_multi_partial_score():
    question = get_question("m2-07")
    result = grade_answer(question, {"first": "10.0.0.1", "last": "10.0.0.127"})
    assert result["correct"] is False
    assert result["score"] == 50
    assert len(result["fields"]) == 2
    assert result["fields"][0]["correct"] is True
    assert result["fields"][1]["correct"] is False

    full = grade_answer(question, {"first": "10.0.0.1", "last": "10.0.0.126"})
    assert full["correct"] is True
    assert full["score"] == 100


def test_choice_grading():
    question = get_question("m1-05")
    assert grade_answer(question, {"value": str(question["correct"])})["correct"] is True
    assert grade_answer(question, {"value": "0"})["correct"] is False
    assert grade_answer(question, {"value": "99"})["correct"] is False


def test_scenario_accepts_synonyms_and_reports_points():
    question = get_question("m1-11")
    answer = (
        "Сначала посмотрю ipconfig /all и адреса DNS. Затем сделаю nslookup, "
        "проверю, что выдал DHCP, открою сайт по IP и пропингую DNS-сервер."
    )
    result = grade_answer(question, {"text": answer})
    assert result["correct"] is True
    assert result["score"] == 100
    assert result["matched"]
    assert result["missed"] == []
    assert result["needs_self_check"] is False


def test_scenario_partial_answer_needs_self_check():
    question = get_question("m1-11")
    result = grade_answer(question, {"text": "Проверю DNS и nslookup."})
    assert result["correct"] is False
    assert result["needs_self_check"] is True
    assert result["matched"]
    assert result["missed"]
    assert 0 < result["score"] < 100


def test_gateway_accepts_any_host_in_subnet():
    question = get_question("m4-06")
    for value in ("192.168.10.1", "192.168.10.2", "192.168.10.254"):
        result = grade_answer(
            question, {"gw10": value, "gw20": "192.168.20.100"}
        )
        assert result["correct"] is True, value

    network_address = grade_answer(
        question, {"gw10": "192.168.10.0", "gw20": "192.168.20.1"}
    )
    assert network_address["correct"] is False
    broadcast = grade_answer(
        question, {"gw10": "192.168.10.255", "gw20": "192.168.20.1"}
    )
    assert broadcast["correct"] is False


def test_empty_answer_is_incorrect():
    question = get_question("m3-08")
    result = grade_answer(question, {"text": "   "})
    assert result["correct"] is False
    assert result["empty"] is True
    assert result["score"] == 0


def test_normalize_text_handles_yo_and_punctuation():
    assert normalize_text("  Ёлка, DNS-сервер! ") == "елка dns сервер"
