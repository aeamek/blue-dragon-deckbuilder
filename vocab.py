"""Locked vocabularies for card type, element/attribute, and the seeded set
list. Sets are extensible — the editor merges these with anything found in
labels.csv (see catalog.sets_seen)."""

KNOWN_TYPES = ("Shadow", "Partner", "Skill", "Command")

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
