"""One canonical display name per exercise, shared by every view.

The JSONL stays verbatim (it is the source of truth), but the sheet and the dashboard
both group by exercise name, and a lift logged under a variant spelling must land in
the same row. Add a line whenever a new variant appears in your log; the examples
below are the kind of drift that shows up after a few months of chat logging.
"""

ALIASES = {
    # >>> SET YOUR OWN <<< variant spelling -> the canonical name you want in the views
    "pallof press (band)": "pallof press",
    "face pull": "face pulls",
    "rdl": "romanian deadlift",
    "ohp": "overhead press",
    "seated overhead press (dumbbell)": "seated dumbbell shoulder press",
}


def canon(name: str) -> str:
    return ALIASES.get(name, name)
