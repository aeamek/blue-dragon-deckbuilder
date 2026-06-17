"""Locked vocabularies for card type, element/attribute, and the seeded set
list. Sets are extensible — the editor merges these with anything found in
labels.csv (see catalog.sets_seen)."""

KNOWN_TYPES = ("Shadow", "Partner", "Skill", "Command")

# Canonical ordering used when sorting cards for display (browser, decklist,
# deck image). Note this differs from KNOWN_TYPES: Command sorts before Skill.
TYPE_ORDER = ("Shadow", "Partner", "Command", "Skill")
_TYPE_RANK = {t: i for i, t in enumerate(TYPE_ORDER)}


def type_rank(type_):
    """Sort rank for a card type; unknown / unlabeled types sort last."""
    return _TYPE_RANK.get(type_, len(TYPE_ORDER))

KNOWN_ELEMENTS = ("light", "dark", "fire", "water", "earth", "wind", "none")

# Types that CANNOT carry an element. The editor hides the element block for
# these; the API forces element=[] on save; the loader warns if it sees one.
TYPES_WITHOUT_ELEMENT = frozenset({"Command", "Skill"})

SEEDED_SETS = (
    "Light Starter",
    "Shadow Starter",
    "Demo Deck",
    "Set 1",
    "Set 2",
    "Parallel Shadows",
)
