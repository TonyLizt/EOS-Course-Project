"""Exact interval-margins kernel, NOT an Orekit provider or formal receipt.

The theorem is conditional on independently validated model enclosures. There
is deliberately no registration with the formal verifier and no JSON authority
token: caller-supplied bounds cannot assert physical truth. See the reviewed
continuous_interval_certification_design.md for the missing Orekit prerequisites.
"""
from dataclasses import dataclass
from fractions import Fraction

VERSION = 'rational-margin-kernel-v1'


def _rational(value):
    if type(value) is int:
        return Fraction(value)
    if type(value) is not Fraction:
        raise TypeError('exact Fraction/int required; floats are not outward intervals')
    return value


@dataclass(frozen=True)
class Bounds:
    lower: Fraction
    upper: Fraction

    def __post_init__(self):
        object.__setattr__(self,'lower',_rational(self.lower))
        object.__setattr__(self,'upper',_rational(self.upper))
        if self.lower>self.upper:raise ValueError('reversed bounds')


def lipschitz_enclosure(value: Bounds, derivative_abs, radius_s):
    """Given TRUE |g'|<=L over the cell and true center value in value.

    This function NEVER estimates L from samples or adds an empirical epsilon.
    The provider must already include all model/input/numeric error in value/L.
    """
    if type(value) is not Bounds:raise TypeError('Bounds required')
    derivative_abs,radius_s=map(_rational,(derivative_abs,radius_s))
    if derivative_abs<0 or radius_s<0:raise ValueError('negative derivative/radius')
    delta=derivative_abs*radius_s
    return Bounds(value.lower-delta,value.upper+delta)


@dataclass(frozen=True)
class Cell:
    first_us: int
    last_us: int
    identity_sha256: str
    # Immutable named bounds covering the ENTIRE closed cell, including all
    # real-valued times between representable microsecond timestamps.
    margins: tuple

    def __post_init__(self):
        if type(self.first_us) is not int or type(self.last_us) is not int or self.first_us>=self.last_us:
            raise ValueError('positive integer-microsecond cell required')
        if not _sha(self.identity_sha256):raise ValueError('invalid model/input identity')
        if type(self.margins) is not tuple:raise TypeError('immutable margin tuple required')
        names=[]
        for row in self.margins:
            if type(row) is not tuple or len(row)!=2 or type(row[0]) is not str or not row[0] or type(row[1]) is not Bounds:
                raise ValueError('invalid named bounds')
            names.append(row[0])
        if len(names)!=len(set(names)):raise ValueError('duplicate margin')


def _sha(value):
    return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True)
class ProofResult:
    status: str
    reason: str
    cells_checked: int
    scope: str = 'ENCLOSURE_HYPOTHESES_ONLY_NOT_PHYSICAL_CERTIFICATION'


def verify_partition(first_us, last_us, cells, requirements, *, identity_sha256, max_cells=4096):
    """requirements=(('margin_name', strict_bool),...); gap-free closed cover.

    PROVED_INEQUALITIES is NOT CONTINUOUS_PASS. The formal pipeline must supply
    an independently validated provider AND a valid execution trajectory first.
    """
    if type(first_us) is not int or type(last_us) is not int or first_us>=last_us:
        raise ValueError('invalid exposure')
    if not _sha(identity_sha256):raise ValueError('invalid expected identity')
    if type(max_cells) is not int or not 1<=max_cells<=100000:raise ValueError('invalid cell budget')
    if type(cells) is not tuple or type(requirements) is not tuple:raise TypeError('immutable input tuples required')
    if not requirements:raise ValueError('no physical requirements')
    for r in requirements:
        if type(r) is not tuple or len(r)!=2 or type(r[0]) is not str or not r[0] or type(r[1]) is not bool:
            raise ValueError('invalid requirement')
    if len({r[0] for r in requirements})!=len(requirements):raise ValueError('duplicate requirement')
    if not cells or len(cells)>max_cells:return ProofResult('INCONCLUSIVE','MISSING_OR_EXCESSIVE_CELLS',0)
    if any(type(c) is not Cell for c in cells):raise TypeError('Cell required')
    ordered=sorted(cells,key=lambda c:c.first_us)
    cursor=first_us
    # Validate complete cover/identity before interpreting any bound.
    for c in ordered:
        if c.identity_sha256!=identity_sha256:return ProofResult('INCONCLUSIVE','MODEL_INPUT_IDENTITY_MISMATCH',0)
        if c.first_us!=cursor or c.last_us>last_us:return ProofResult('INCONCLUSIVE','GAP_OVERLAP_OR_OUTSIDE_EXPOSURE',0)
        if {n for n,b in c.margins}!={n for n,strict in requirements}:
            return ProofResult('INCONCLUSIVE','MISSING_OR_UNEXPECTED_MARGIN',0)
        cursor=c.last_us
    if cursor!=last_us:return ProofResult('INCONCLUSIVE','INCOMPLETE_EXPOSURE_COVERAGE',0)
    unknown=False
    for index,c in enumerate(ordered,1):
        bounds=dict(c.margins)
        for name,strict in requirements:
            interval=bounds[name]
            if interval.upper<0 or (strict and interval.upper==0):
                return ProofResult('REFUTED_INEQUALITY',name,index)
            if interval.lower<0 or (strict and interval.lower==0):unknown=True
    return ProofResult('INCONCLUSIVE' if unknown else 'PROVED_INEQUALITIES',
                       'BOUND_STRADDLES_LIMIT' if unknown else 'EXACT_ENCLOSURES_COVER_EXPOSURE',len(ordered))
