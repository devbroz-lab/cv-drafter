"""
Tests for pipeline.utils.countries.find_countries — deterministic country-name
detection from free-text location strings.
"""

from pipeline.utils.countries import find_countries


class TestRealWorldLocations:
    def test_city_slash_country(self):
        assert find_countries("Essen / Germany") == ["Germany"]

    def test_comma_separated_multi_country(self):
        assert find_countries("Sri Lanka, India, Bhutan, Nepal, Bangladesh") == [
            "Sri Lanka", "India", "Bhutan", "Nepal", "Bangladesh",
        ]

    def test_two_city_country_pairs(self):
        assert find_countries("Kabul, Afghanistan / Baden, Switzerland") == [
            "Afghanistan", "Switzerland",
        ]

    def test_misspelling_via_alias(self):
        # "Kyrgystan" (missing the second z) is a real-CV misspelling.
        assert find_countries("Afghanistan, Tajikistan, Kyrgystan and Pakistan") == [
            "Afghanistan", "Tajikistan", "Kyrgyzstan", "Pakistan",
        ]


class TestRegionsAndCitiesExcluded:
    def test_region_not_matched(self):
        assert find_countries("Afghanistan / South & Central Asia / Germany") == [
            "Afghanistan", "Germany",
        ]

    def test_region_only_returns_empty(self):
        assert find_countries("South & Central Asia") == []

    def test_city_only_returns_empty(self):
        assert find_countries("Gräfenberg") == []
        assert find_countries("Essen") == []


class TestAliases:
    def test_country_inside_formal_name(self):
        # "Republic of Gambia" — word-boundary match on "Gambia".
        assert find_countries("Republic of Gambia") == ["Gambia"]

    def test_abbreviations(self):
        assert find_countries("USA and UK") == ["United States", "United Kingdom"]

    def test_ivory_coast(self):
        assert find_countries("Abidjan, Ivory Coast") == ["Ivory Coast"]

    def test_russian_federation(self):
        assert find_countries("Russian Federation") == ["Russia"]


class TestBoundarySafety:
    def test_nigeria_not_niger(self):
        assert find_countries("Lagos, Nigeria") == ["Nigeria"]

    def test_niger_distinct_from_nigeria(self):
        assert find_countries("Niamey, Niger") == ["Niger"]

    def test_south_sudan_wins_over_sudan(self):
        assert find_countries("Juba, South Sudan") == ["South Sudan"]

    def test_south_sudan_and_sudan_both(self):
        assert find_countries("South Sudan and Sudan") == ["South Sudan", "Sudan"]

    def test_guinea_bissau_distinct(self):
        assert find_countries("Guinea-Bissau and Guinea") == ["Guinea-Bissau", "Guinea"]

    def test_dominican_republic_distinct(self):
        assert find_countries("Dominican Republic and Dominica") == [
            "Dominican Republic", "Dominica",
        ]


class TestSemantics:
    def test_case_insensitive(self):
        assert find_countries("germany / FRANCE / Italy") == ["Germany", "France", "Italy"]

    def test_dedup_first_occurrence_order(self):
        assert find_countries("Germany, France, Germany") == ["Germany", "France"]

    def test_empty_and_none(self):
        assert find_countries("") == []
        assert find_countries(None) == []

    def test_no_country_returns_empty(self):
        assert find_countries("123 Main Street, Remote") == []
