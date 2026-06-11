"""
Deterministic country-name detection for free-text location strings.

Used by the Agent 1 countries_of_experience fallback (cv_extractor.py) to
derive the countries a candidate has worked in from project / employment
location fields such as:

    "Essen / Germany"
    "Kabul, Afghanistan / Baden, Switzerland"
    "Sri Lanka, India, Bhutan, Nepal, Bangladesh"
    "Afghanistan, Tajikistan, Kyrgystan and Pakistan"

Matching is intentionally exact (word-boundary, case-insensitive) against a
static list of ISO-3166 short names plus a curated alias table — no fuzzy
matching. Cities, regions ("South & Central Asia"), and unknown spellings
simply produce no match; the caller decides what an empty result means.
"""

from __future__ import annotations

import re

# ISO-3166 short names (Title Case), plus a handful of widely used short forms
# that ARE the common name (e.g. "Russia", "Iran", "Syria") so plain CV text
# matches without needing the alias table.
COUNTRY_NAMES: tuple[str, ...] = (
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola",
    "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus",
    "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon",
    "Canada", "Central African Republic", "Chad", "Chile", "China",
    "Colombia", "Comoros", "Costa Rica", "Croatia", "Cuba", "Cyprus",
    "Czech Republic", "Democratic Republic of the Congo", "Denmark",
    "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt",
    "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini",
    "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia",
    "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea",
    "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hungary", "Iceland",
    "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy",
    "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati",
    "Kosovo", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon",
    "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali",
    "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico",
    "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco",
    "Mozambique", "Myanmar", "Namibia", "Nauru", "Nepal", "Netherlands",
    "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea",
    "North Macedonia", "Norway", "Oman", "Pakistan", "Palau", "Palestine",
    "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines",
    "Poland", "Portugal", "Qatar", "Republic of the Congo", "Romania",
    "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia",
    "Saint Vincent and the Grenadines", "Samoa", "San Marino",
    "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia",
    "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia",
    "Solomon Islands", "Somalia", "South Africa", "South Korea",
    "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden",
    "Switzerland", "Syria", "Taiwan", "Tajikistan", "Tanzania", "Thailand",
    "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", "Tunisia",
    "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay",
    "Uzbekistan", "Vanuatu", "Venezuela", "Vietnam", "Yemen", "Zambia",
    "Zimbabwe",
)

# Lowercase alias → canonical name. Abbreviations, official long forms,
# historic/common variants, and real-CV misspellings. Word-boundary matching
# already covers prefixed forms like "Republic of Gambia" (hits "Gambia"),
# so only spellings that contain no canonical name need an entry here.
COUNTRY_ALIASES: dict[str, str] = {
    # Abbreviations
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "drc": "Democratic Republic of the Congo",
    "dr congo": "Democratic Republic of the Congo",
    "car": "Central African Republic",
    "png": "Papua New Guinea",
    # Official / long forms
    "united states of america": "United States",
    "great britain": "United Kingdom",
    "russian federation": "Russia",
    "republic of korea": "South Korea",
    "korea, republic of": "South Korea",
    "democratic people's republic of korea": "North Korea",
    "lao pdr": "Laos",
    "lao people's democratic republic": "Laos",
    "viet nam": "Vietnam",
    "brunei darussalam": "Brunei",
    "syrian arab republic": "Syria",
    "islamic republic of iran": "Iran",
    "kingdom of saudi arabia": "Saudi Arabia",
    "the netherlands": "Netherlands",
    "the gambia": "Gambia",
    "the bahamas": "Bahamas",
    # Common / historic variants
    "ivory coast": "Ivory Coast",
    "cote d'ivoire": "Ivory Coast",
    "côte d'ivoire": "Ivory Coast",
    "burma": "Myanmar",
    "czechia": "Czech Republic",
    "swaziland": "Eswatini",
    "macedonia": "North Macedonia",
    "fyrom": "North Macedonia",
    "cape verde": "Cabo Verde",
    "east timor": "Timor-Leste",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "korea": "South Korea",
    "congo": "Republic of the Congo",
    "holland": "Netherlands",
    "uk of great britain and northern ireland": "United Kingdom",
    # Real-CV misspellings (seen in production runs)
    "kyrgystan": "Kyrgyzstan",
    "kirgizstan": "Kyrgyzstan",
    "kirghizstan": "Kyrgyzstan",
    "kazakstan": "Kazakhstan",
    "tadjikistan": "Tajikistan",
    "afganistan": "Afghanistan",
}

# Canonical lookup for every matchable spelling (lowercase → canonical).
_CANONICAL: dict[str, str] = {name.lower(): name for name in COUNTRY_NAMES}
_CANONICAL.update(COUNTRY_ALIASES)

# Single compiled pattern, longest spelling first so multi-word names win over
# their substrings (South Sudan vs Sudan, Guinea-Bissau / Papua New Guinea vs
# Guinea, Dominican Republic vs Dominica). (?<!\w)/(?!\w) word boundaries
# protect Niger vs Nigeria while still matching next to punctuation ("/Germany").
_PATTERN = re.compile(
    "|".join(
        f"(?<!\\w){re.escape(spelling)}(?!\\w)"
        for spelling in sorted(_CANONICAL, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


def find_countries(text: str) -> list[str]:
    """
    Return the canonical country names found in *text*, in first-appearance
    order, deduplicated. Empty/None input returns [].
    """
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _PATTERN.finditer(text):
        canonical = _CANONICAL[match.group(0).lower()]
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found
