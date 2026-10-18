"""Narrow compatibility for a documented presentation-only registry regression.

These are complete execution-source digests, not Git IDs or registry-only hashes.
The two trees differ only by parameter title/description enrichment in the
registry (main 3e9413d versus UI commit 63b35a1). Any solver/constraint/source
change changes the full digest and is NOT accepted by this exception.
"""

PRESENTATION_ONLY_SOURCE_PAIR = frozenset({
    '382612be7cac60c70c16272fcf34a9289d1365c0e336ab775e7322c76a8967f4',
    '149dd9bb3e87cb227cc1bb72d3356cd73d76c30376ad3f01f81dffc064cdc602',
})


def presentation_only_source_change(previous, current):
    return previous != current and {previous, current} == PRESENTATION_ONLY_SOURCE_PAIR
