"""A small built-in airport list for the search form's autocomplete.

Deliberately bundled rather than fetched from an API: the search form needs to
turn "new york" into `JFK` instantly and offline, and a few hundred rows of
static data is far simpler than another network dependency for a local tool.

This is major commercial airports only, not a complete registry. The form
still accepts any 3-letter code typed directly, so an airport missing from
this list is an autocomplete gap, never a blocked search.
"""

from __future__ import annotations

from typing import NamedTuple


class Airport(NamedTuple):
    code: str
    name: str
    city: str
    country: str

    @property
    def label(self) -> str:
        return f"{self.city} ({self.code}) - {self.name}"


# (code, airport name, city, country)
_RAW: tuple[tuple[str, str, str, str], ...] = (
    # --- North America ---
    ("ATL", "Hartsfield-Jackson Atlanta International", "Atlanta", "United States"),
    ("AUS", "Austin-Bergstrom International", "Austin", "United States"),
    ("BNA", "Nashville International", "Nashville", "United States"),
    ("BOS", "Logan International", "Boston", "United States"),
    ("BWI", "Baltimore/Washington International", "Baltimore", "United States"),
    ("CLT", "Charlotte Douglas International", "Charlotte", "United States"),
    ("DCA", "Ronald Reagan Washington National", "Washington", "United States"),
    ("DEN", "Denver International", "Denver", "United States"),
    ("DFW", "Dallas/Fort Worth International", "Dallas", "United States"),
    ("DTW", "Detroit Metropolitan Wayne County", "Detroit", "United States"),
    ("EWR", "Newark Liberty International", "New York", "United States"),
    ("FLL", "Fort Lauderdale-Hollywood International", "Fort Lauderdale", "United States"),
    ("HNL", "Daniel K. Inouye International", "Honolulu", "United States"),
    ("IAD", "Washington Dulles International", "Washington", "United States"),
    ("IAH", "George Bush Intercontinental", "Houston", "United States"),
    ("JFK", "John F. Kennedy International", "New York", "United States"),
    ("LAS", "Harry Reid International", "Las Vegas", "United States"),
    ("LAX", "Los Angeles International", "Los Angeles", "United States"),
    ("LGA", "LaGuardia", "New York", "United States"),
    ("MCO", "Orlando International", "Orlando", "United States"),
    ("MDW", "Chicago Midway International", "Chicago", "United States"),
    ("MIA", "Miami International", "Miami", "United States"),
    ("MSP", "Minneapolis-Saint Paul International", "Minneapolis", "United States"),
    ("ORD", "O'Hare International", "Chicago", "United States"),
    ("PDX", "Portland International", "Portland", "United States"),
    ("PHL", "Philadelphia International", "Philadelphia", "United States"),
    ("PHX", "Phoenix Sky Harbor International", "Phoenix", "United States"),
    ("RDU", "Raleigh-Durham International", "Raleigh", "United States"),
    ("SAN", "San Diego International", "San Diego", "United States"),
    ("SEA", "Seattle-Tacoma International", "Seattle", "United States"),
    ("SFO", "San Francisco International", "San Francisco", "United States"),
    ("SJC", "Norman Y. Mineta San Jose International", "San Jose", "United States"),
    ("SLC", "Salt Lake City International", "Salt Lake City", "United States"),
    ("STL", "St. Louis Lambert International", "St. Louis", "United States"),
    ("TPA", "Tampa International", "Tampa", "United States"),
    ("YUL", "Montreal-Trudeau International", "Montreal", "Canada"),
    ("YVR", "Vancouver International", "Vancouver", "Canada"),
    ("YYC", "Calgary International", "Calgary", "Canada"),
    ("YYZ", "Toronto Pearson International", "Toronto", "Canada"),
    ("CUN", "Cancun International", "Cancun", "Mexico"),
    ("GDL", "Guadalajara International", "Guadalajara", "Mexico"),
    ("MEX", "Mexico City International", "Mexico City", "Mexico"),
    ("PANAMA_PTY", "Tocumen International", "Panama City", "Panama"),
    # --- South America ---
    ("BOG", "El Dorado International", "Bogota", "Colombia"),
    ("EZE", "Ministro Pistarini International", "Buenos Aires", "Argentina"),
    ("GIG", "Rio de Janeiro/Galeao International", "Rio de Janeiro", "Brazil"),
    ("GRU", "Sao Paulo/Guarulhos International", "Sao Paulo", "Brazil"),
    ("LIM", "Jorge Chavez International", "Lima", "Peru"),
    ("SCL", "Arturo Merino Benitez International", "Santiago", "Chile"),
    # --- Europe ---
    ("AMS", "Amsterdam Airport Schiphol", "Amsterdam", "Netherlands"),
    ("ARN", "Stockholm Arlanda", "Stockholm", "Sweden"),
    ("ATH", "Athens International", "Athens", "Greece"),
    ("BCN", "Josep Tarradellas Barcelona-El Prat", "Barcelona", "Spain"),
    ("BER", "Berlin Brandenburg", "Berlin", "Germany"),
    ("BRU", "Brussels Airport", "Brussels", "Belgium"),
    ("BUD", "Budapest Ferenc Liszt International", "Budapest", "Hungary"),
    ("CDG", "Charles de Gaulle", "Paris", "France"),
    ("CPH", "Copenhagen Airport", "Copenhagen", "Denmark"),
    ("DUB", "Dublin Airport", "Dublin", "Ireland"),
    ("DUS", "Dusseldorf Airport", "Dusseldorf", "Germany"),
    ("EDI", "Edinburgh Airport", "Edinburgh", "United Kingdom"),
    ("FCO", "Leonardo da Vinci-Fiumicino", "Rome", "Italy"),
    ("FRA", "Frankfurt Airport", "Frankfurt", "Germany"),
    ("GVA", "Geneva Airport", "Geneva", "Switzerland"),
    ("HEL", "Helsinki-Vantaa", "Helsinki", "Finland"),
    ("IST", "Istanbul Airport", "Istanbul", "Turkey"),
    ("LGW", "Gatwick", "London", "United Kingdom"),
    ("LHR", "Heathrow", "London", "United Kingdom"),
    ("LIS", "Humberto Delgado", "Lisbon", "Portugal"),
    ("MAD", "Adolfo Suarez Madrid-Barajas", "Madrid", "Spain"),
    ("MAN", "Manchester Airport", "Manchester", "United Kingdom"),
    ("MUC", "Munich Airport", "Munich", "Germany"),
    ("MXP", "Milan Malpensa", "Milan", "Italy"),
    ("OSL", "Oslo Airport Gardermoen", "Oslo", "Norway"),
    ("PRG", "Vaclav Havel Airport Prague", "Prague", "Czechia"),
    ("STN", "Stansted", "London", "United Kingdom"),
    ("VIE", "Vienna International", "Vienna", "Austria"),
    ("WAW", "Warsaw Chopin", "Warsaw", "Poland"),
    ("ZRH", "Zurich Airport", "Zurich", "Switzerland"),
    # --- Middle East & Africa ---
    ("ABV", "Nnamdi Azikiwe International", "Abuja", "Nigeria"),
    ("ADD", "Addis Ababa Bole International", "Addis Ababa", "Ethiopia"),
    ("AUH", "Zayed International", "Abu Dhabi", "United Arab Emirates"),
    ("CAI", "Cairo International", "Cairo", "Egypt"),
    ("CPT", "Cape Town International", "Cape Town", "South Africa"),
    ("DOH", "Hamad International", "Doha", "Qatar"),
    ("DXB", "Dubai International", "Dubai", "United Arab Emirates"),
    ("JNB", "O. R. Tambo International", "Johannesburg", "South Africa"),
    ("LOS", "Murtala Muhammed International", "Lagos", "Nigeria"),
    ("NBO", "Jomo Kenyatta International", "Nairobi", "Kenya"),
    ("RUH", "King Khalid International", "Riyadh", "Saudi Arabia"),
    ("TLV", "Ben Gurion", "Tel Aviv", "Israel"),
    # --- Asia ---
    ("BKK", "Suvarnabhumi", "Bangkok", "Thailand"),
    ("BLR", "Kempegowda International", "Bengaluru", "India"),
    ("BOM", "Chhatrapati Shivaji Maharaj International", "Mumbai", "India"),
    ("CAN", "Guangzhou Baiyun International", "Guangzhou", "China"),
    ("CEB", "Mactan-Cebu International", "Cebu", "Philippines"),
    ("CGK", "Soekarno-Hatta International", "Jakarta", "Indonesia"),
    ("DEL", "Indira Gandhi International", "Delhi", "India"),
    ("DPS", "Ngurah Rai International", "Denpasar", "Indonesia"),
    ("HAN", "Noi Bai International", "Hanoi", "Vietnam"),
    ("HKG", "Hong Kong International", "Hong Kong", "Hong Kong"),
    ("HND", "Tokyo Haneda", "Tokyo", "Japan"),
    ("ICN", "Incheon International", "Seoul", "South Korea"),
    ("KIX", "Kansai International", "Osaka", "Japan"),
    ("KUL", "Kuala Lumpur International", "Kuala Lumpur", "Malaysia"),
    ("MNL", "Ninoy Aquino International", "Manila", "Philippines"),
    ("NRT", "Tokyo Narita", "Tokyo", "Japan"),
    ("PEK", "Beijing Capital International", "Beijing", "China"),
    ("PVG", "Shanghai Pudong International", "Shanghai", "China"),
    ("SGN", "Tan Son Nhat International", "Ho Chi Minh City", "Vietnam"),
    ("SIN", "Changi", "Singapore", "Singapore"),
    ("TPE", "Taiwan Taoyuan International", "Taipei", "Taiwan"),
    # --- Oceania ---
    ("AKL", "Auckland Airport", "Auckland", "New Zealand"),
    ("BNE", "Brisbane Airport", "Brisbane", "Australia"),
    ("CHC", "Christchurch International", "Christchurch", "New Zealand"),
    ("MEL", "Melbourne Airport", "Melbourne", "Australia"),
    ("PER", "Perth Airport", "Perth", "Australia"),
    ("SYD", "Sydney Kingsford Smith", "Sydney", "Australia"),
)

AIRPORTS: tuple[Airport, ...] = tuple(
    Airport(code, name, city, country)
    for code, name, city, country in _RAW
    # Guard against a malformed entry reaching the autocomplete as a bad code.
    if len(code) == 3
)

_BY_CODE: dict[str, Airport] = {airport.code: airport for airport in AIRPORTS}

#: Autocomplete never returns more than this many rows.
MAX_SUGGESTIONS = 8


def get_airport(code: str) -> Airport | None:
    return _BY_CODE.get((code or "").strip().upper())


def describe(code: str) -> str:
    """"JFK" -> "New York (JFK)", falling back to the bare code if unknown."""
    airport = get_airport(code)
    return f"{airport.city} ({airport.code})" if airport else (code or "").upper()


def search_airports(term: str, limit: int = MAX_SUGGESTIONS) -> list[Airport]:
    """Airports matching `term` by code, city, airport name or country.

    Ranked so that the thing a user most likely meant comes first: an exact
    code match, then a city or code prefix, then anything containing the term.
    """
    needle = (term or "").strip().lower()
    if not needle:
        return []

    exact: list[Airport] = []
    prefix: list[Airport] = []
    contains: list[Airport] = []

    for airport in AIRPORTS:
        code = airport.code.lower()
        city = airport.city.lower()
        name = airport.name.lower()
        country = airport.country.lower()

        if code == needle:
            exact.append(airport)
        elif code.startswith(needle) or city.startswith(needle):
            prefix.append(airport)
        elif needle in city or needle in name or needle in country:
            contains.append(airport)

    return (exact + prefix + contains)[:limit]
