"""The exercise-burn calculation step (FTY-043).

The second real estimation pipeline step. It takes the exercise candidates the
parse step (FTY-042) extracted and costs each into **net active calories** with the
deterministic, curated-MET calculator (:mod:`app.estimator.exercise`), using the
user's body weight loaded onto the context by the worker. Food candidates are left
untouched (resolution is FTY-044).

Routing follows FTY-042's conventions:

- **all candidates resolve** → record :class:`~app.estimator.pipeline.ResolvedExerciseItem`
  results on the context; the worker persists them ``resolved`` with their
  ``active_calories`` and completes the event.
- **unknown activity / missing or implausible duration** → raise
  :class:`~app.estimator.pipeline.NeedsClarification`; the input is recognisably
  exercise but cannot be costed confidently, so the user is asked (terminal, not a
  guess). A fixed, sanitized question is recorded for the answer flow.
- **missing body weight** → raise
  :class:`~app.estimator.pipeline.StepFailed`; the profile is incomplete, so the
  burn cannot be computed and the event fails closed (deterministic, non-retryable).

The MET value is never taken from the model — only the curated table — and the run
records the table **version/source** and the net-active formula as evidence, never
the user's weight or any raw text (security baseline + ``docs/security/data-retention.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.estimator.evidence_utils import _record_source_ref
from app.estimator.exercise import (
    NET_ACTIVE_FORMULA,
    InvalidDurationError,
    MissingBodyWeightError,
    UnknownActivityError,
    resolve_exercise,
)
from app.estimator.met_table import MET_TABLE_SOURCE, MET_TABLE_VERSION
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedExerciseItem,
    StepFailed,
)

#: Fixed, sanitized clarification questions. Used in place of any raw user text so a
#: ``needs_clarification`` outcome always carries a question for the later answer flow.
UNKNOWN_ACTIVITY_QUESTION = "Which exercise did you do? We couldn't match that activity."
DURATION_QUESTION = "How long did that exercise last (for example, in minutes)?"


@dataclass(frozen=True)
class ExerciseCalculateStep:
    """Cost the parsed exercise candidates into net active calories (FTY-043)."""

    name: str = "exercise_calculate"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        if not context.exercise_candidates:
            # Nothing to cost (e.g. a food-only event). Record the step and leave
            # the run evidence untouched — no MET table was consulted.
            context.record_step(self.name, "ok")
            return

        self._record_evidence(context)

        for candidate in context.exercise_candidates:
            context.resolved_exercise_items.append(self._resolve(context, candidate))

        context.record_step(self.name, "ok")

    def _resolve(
        self, context: EstimationContext, candidate: CandidateDraft
    ) -> ResolvedExerciseItem:
        """Resolve one candidate, mapping calculator errors to pipeline signals."""

        try:
            burn = resolve_exercise(
                activity=candidate.name,
                weight_kg=context.weight_kg,
                unit=candidate.unit,
                amount=candidate.amount,
                quantity_text=candidate.quantity_text,
            )
        except UnknownActivityError as exc:
            context.clarification_questions = [UNKNOWN_ACTIVITY_QUESTION]
            raise NeedsClarification(exc.reason) from exc
        except InvalidDurationError as exc:
            context.clarification_questions = [DURATION_QUESTION]
            raise NeedsClarification(exc.reason) from exc
        except MissingBodyWeightError as exc:
            # An incomplete profile, not an ambiguous log: fail closed rather than
            # ask a question the answer flow cannot resolve.
            raise StepFailed(exc.reason) from exc

        # Surface any duration-inference assumption (distance/steps/games → minutes)
        # on the run so the conversion is visible; content-free metadata only.
        for assumption in burn.assumptions:
            if assumption not in context.assumptions:
                context.assumptions.append(assumption)

        return ResolvedExerciseItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            met=burn.met,
            duration_minutes=burn.duration_minutes,
            active_calories=burn.active_calories,
        )

    @staticmethod
    def _record_evidence(context: EstimationContext) -> None:
        """Record the curated MET table version/source and formula as run evidence.

        Sanitized, content-free metadata only — the table version, its source, and
        the net-active formula — never the user's weight or any raw text.
        """

        version_ref = f"met_table:{MET_TABLE_VERSION}"
        _record_source_ref(context, version_ref)
        _record_source_ref(context, MET_TABLE_SOURCE)
        if NET_ACTIVE_FORMULA not in context.assumptions:
            context.assumptions.append(NET_ACTIVE_FORMULA)
            context.assumptions.append(f"met_table_version={MET_TABLE_VERSION}")
