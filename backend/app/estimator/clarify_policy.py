"""The calibrated clarify/estimate decision policy (FTY-159, ADR 0003 Layer C).

Both estimation gates that decide "trust this as an estimate vs ask the user"
route through one mechanism here: a :class:`ClarifyPolicy` names the signal the
gate scores, the operating threshold, and the basis that threshold rests on.
This replaces the two retired hand-picked constants
(``PARSE_CONFIDENCE_CLARIFY_THRESHOLD = 0.45`` in ``parse.py`` and
``LABEL_CONFIDENCE_CLARIFY_THRESHOLD = 0.5`` in ``label_step.py``) — a fixed
threshold guessed without calibration data is fragile under distribution shift
(Kamath, Jia & Liang, ACL 2020; see
``docs/adr/0003-estimator-confidence-clarification.md``).

**NL parse gate** (:data:`NL_PARSE_CLARIFY_POLICY`): the signal and threshold
are *measured*, not chosen by hand. The FTY-159 bake-off scored the verbalized
baseline, the FTY-158 self-consistency agreement signal, and their hybrid over
the combined labeled calibration set (FTY-157 synthetic + FTY-169 naturalistic
bands, 325 examples) via risk-coverage curves
(``tests/parse_calibration/harness.py``, ``run_bake_off``). The **hybrid** won:
at the target answered precision (≥ 0.99 of estimated events must be
gold-estimate — under-asking silently corrupts an honest count, so precision is
the calibration target) it reaches 63.1% coverage where the verbalized baseline
manages 40.0% and agreement-only never reaches the target at all. The operating
threshold is the midpoint of the empirical margin band around that operating
point, giving measured over-ask 6.5% / under-ask 1.9% versus the retired
verbalized-vs-0.45 gate's 12.4% / 19.4% on the same set. The committed
derivation is ``tests/fixtures/parse_calibration/calibration_summary.json``;
``tests/test_clarify_calibration.py`` re-derives it on every run and fails if
this constant drifts from the data — a prompt or model change that degrades the
operating point past its floors fails verification and requires recalibrating
against the harness (ADR 0003, Consequences).

Temperature scaling (Guo et al., ICML 2017) was considered and deliberately not
fit: it is a monotone transform of the score, so for a single-threshold
decision it cannot change any routing — choosing the threshold directly on the
risk-coverage curve is the same one-parameter calibration without a second
moving part. The margin-band midpoint plays the conformal-abstention role
(Yadkori et al., 2024) at this data size: the cutoff sits strictly between the
observed score clusters rather than on one.

**Label gate** (:data:`LABEL_CLARIFY_POLICY`): same mechanism, but its
operating point is a **documented tunable, not a data-derived one** — the
calibration sets are NL-parse descriptions, and pretending a label-image
operating point falls out of them would fabricate a calibration. It keeps the
conservative pre-FTY-159 value until a dedicated label-image eval slice (the
sibling follow-up recorded in the FTY-159 story) earns a measured point; the
``basis`` field says so honestly.

Fail-closed invariant: a policy only ever decides *estimate vs ask*. Everything
that fails closed today — schema-invalid output, unparseable input, the
deterministic plausibility gate (FTY-156), a sample set that never parses —
stays upstream of the score comparison and is untouched by calibration.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How a policy's operating threshold was chosen — data-derived on labeled
#: calibration sets, or a documented tunable awaiting its own eval slice.
BASIS_DATA_CALIBRATED = "data_calibrated"
BASIS_DOCUMENTED_TUNABLE = "documented_tunable"


@dataclass(frozen=True)
class ClarifyPolicy:
    """One gate's clarify/estimate decision: signal, operating point, basis.

    ``signal`` names the score the gate must feed in (a contract with the call
    site, pinned by tests — wiring a different signal against a threshold
    calibrated for another one would be meaningless). ``score`` semantics:
    confidence-that-this-should-be-estimated, in [0, 1].
    """

    #: The signal the threshold was calibrated over.
    signal: str
    #: The operating cutoff: scores strictly below it clarify.
    threshold: float
    #: Provenance of the threshold (:data:`BASIS_DATA_CALIBRATED` or
    #: :data:`BASIS_DOCUMENTED_TUNABLE`).
    basis: str

    def should_clarify(self, score: float) -> bool:
        """Whether a score routes to a clarifying question (fail closed: ``<``)."""

        return score < self.threshold


#: The NL parse gate's calibrated decision (derivation in the module docstring):
#: the FTY-158 hybrid self-consistency signal at the bake-off's operating point
#: over the combined FTY-157 + FTY-169 labeled sets. The threshold value must
#: equal the committed ``calibration_summary.json`` winner —
#: ``tests/test_clarify_calibration.py`` enforces it.
NL_PARSE_CLARIFY_POLICY = ClarifyPolicy(
    signal="hybrid_self_consistency",
    threshold=0.702,
    basis=BASIS_DATA_CALIBRATED,
)

#: The nutrition-label gate's decision: the panel's verbalized confidence at the
#: conservative pre-FTY-159 operating point, carried as a documented tunable —
#: no label-image labeled set exists yet to derive it from (see the module
#: docstring). Unifying the mechanism now means the eventual label-image eval
#: slice only has to update this value and its basis, not re-plumb the gate.
LABEL_CLARIFY_POLICY = ClarifyPolicy(
    signal="verbalized_confidence",
    threshold=0.5,
    basis=BASIS_DOCUMENTED_TUNABLE,
)
