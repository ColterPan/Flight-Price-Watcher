from flight_fare_watcher.airports import AIRPORTS, describe, get_airport, search_airports


def test_every_airport_has_a_three_letter_code():
    for airport in AIRPORTS:
        assert len(airport.code) == 3
        assert airport.code.isupper()


def test_codes_are_unique():
    codes = [airport.code for airport in AIRPORTS]
    assert len(codes) == len(set(codes))


def test_get_airport_is_case_insensitive():
    assert get_airport("jfk") is not None
    assert get_airport("JFK").city == "New York"


def test_get_airport_returns_none_for_unknown_code():
    assert get_airport("ZZZ") is None


def test_describe_known_code():
    assert describe("lax") == "Los Angeles (LAX)"


def test_describe_unknown_code_falls_back_to_bare_code():
    assert describe("zzz") == "ZZZ"


def test_search_airports_exact_code_match_ranks_first():
    results = search_airports("sfo")
    assert results[0].code == "SFO"


def test_search_airports_matches_city_name():
    results = search_airports("los angeles")
    assert any(a.code == "LAX" for a in results)


def test_search_airports_matches_partial_city_name():
    results = search_airports("angel")
    assert any(a.code == "LAX" for a in results)


def test_search_airports_respects_limit():
    results = search_airports("a", limit=3)
    assert len(results) <= 3


def test_search_airports_empty_term_returns_nothing():
    assert search_airports("") == []
    assert search_airports("   ") == []


def test_search_airports_prefix_match_ranks_above_contains_match():
    # "london" should surface LHR/LGW/STN (city prefix) before anything that
    # merely contains "london" elsewhere.
    results = search_airports("london")
    assert results[0].city == "London"
