import ipaddress

import pytest

from content import get_question


def network(value):
    return ipaddress.IPv4Network(value, strict=False)


def test_mask_questions_match_ipaddress():
    cases = {
        "m2-01": "/26",
        "m2-02": "/27",
        "m2-03": "/25",
        "m2-04": "/29",
    }
    for question_id, prefix in cases.items():
        question = get_question(question_id)
        result = network("0.0.0.0" + prefix)
        expected = str(result.netmask) if question_id != "m2-04" else "/29"
        assert question["answers"][0] == expected


def test_network_and_broadcast_answers():
    net = network("192.168.10.130/26")
    assert str(net.network_address) == "192.168.10.128"
    assert str(net.broadcast_address) == "192.168.10.191"
    assert get_question("m2-05")["answers"][0] == "192.168.10.128"
    assert get_question("m2-06")["answers"][0] == "192.168.10.191"


def test_host_range_answers():
    net = network("10.0.0.0/25")
    hosts = list(net.hosts())
    question = get_question("m2-07")
    assert question["fields"][0]["answers"][0] == str(hosts[0])
    assert question["fields"][1]["answers"][0] == str(hosts[-1])
    assert net.num_addresses - 2 == 126


def test_usable_host_counts():
    assert network("0.0.0.0/27").num_addresses - 2 == 30
    assert network("0.0.0.0/28").num_addresses - 2 == 14
    assert get_question("m2-08")["answers"][0] == "30"
    assert get_question("m2-09")["answers"][0] == "14"


def test_four_subnets_answers():
    first = list(network("192.168.10.0/24").subnets(new_prefix=26))[0]
    question = get_question("m2-10")
    assert str(first.network_address) == "192.168.10.0"
    assert str(first.broadcast_address) == "192.168.10.63"
    assert question["fields"][0]["answers"][0] == "/26"
    assert question["fields"][1]["answers"][0] == str(first.network_address)
    assert question["fields"][2]["answers"][0] == str(first.broadcast_address)


def test_eight_subnets_third_subnet():
    third = list(network("172.16.5.0/24").subnets(new_prefix=27))[2]
    question = get_question("m2-13")
    assert str(third.network_address) == "172.16.5.64"
    assert str(third.broadcast_address) == "172.16.5.95"
    assert question["fields"][1]["answers"][0] == str(third.network_address)
    assert question["fields"][2]["answers"][0] == str(third.broadcast_address)


def test_slash_23_broadcast():
    net = network("10.10.10.0/23")
    assert str(net.broadcast_address) == "10.10.11.255"
    assert get_question("m2-14")["answers"][0] == "10.10.11.255"


@pytest.mark.parametrize(
    "address,prefix,network_address",
    [
        ("192.168.1.200", 27, "192.168.1.192"),
        ("192.168.10.130", 26, "192.168.10.128"),
        ("172.16.5.100", 27, "172.16.5.96"),
    ],
)
def test_network_address_calculation(address, prefix, network_address):
    net = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
    assert str(net.network_address) == network_address


def test_same_subnet_check_used_in_question():
    first = ipaddress.IPv4Address("192.168.1.10") in network("192.168.1.0/26")
    second = ipaddress.IPv4Address("192.168.1.70") in network("192.168.1.0/26")
    assert first is True
    assert second is False
