"""Documented assumptions for the deterministic target calculator (FTY-022).

Every magic number the calculator depends on lives here, with its source and the
reason the value was chosen, so the contract, the story, and the code all point
at one place. These are deliberately conservative defaults; a later adaptive
calibration story (explicitly out of scope here) may refine them from observed
weight trend.

References
---------
- Mifflin MD, St Jeor ST, et al. "A new predictive equation for resting energy
  expenditure in healthy individuals." *Am J Clin Nutr* 1990;51(2):241-247.
- NIDDK / NIH Body Weight Planner; Hall KD, et al. "Quantification of the effect
  of energy imbalance on bodyweight." *Lancet* 2011;378(9793):826-837. The model
  below is a single-compartment *linearization* of that dynamic energy-balance
  idea, not the full multi-compartment Hall model (see ``calculator`` docstring).
"""

from __future__ import annotations

from typing import Final

#: Baseline (sedentary) activity multiplier applied to RMR to get TDEE.
#: The classic Harris-Benedict/Mifflin "sedentary" PAL factor is 1.2. Logged
#: exercise burn is added to the daily allowance separately by later logging
#: stories and is deliberately NOT folded into this multiplier, to avoid
#: double-counting MET-based active calories (see the story non-goals).
BASELINE_ACTIVITY_MULTIPLIER: Final[float] = 1.2

#: Energy density of body-weight change, kcal per kilogram. ~7700 kcal/kg is the
#: widely used value (the familiar "3500 kcal per pound" rule, ~7716 kcal/kg).
ENERGY_DENSITY_KCAL_PER_KG: Final[float] = 7700.0

#: Sensitivity of daily energy expenditure to body mass, kcal/(kg·day). This is
#: the Mifflin-St Jeor coefficient on weight (the ``10 · weight_kg`` term); it is
#: the single parameter that makes the goal model *dynamic* — expenditure falls
#: as mass falls. Multiplied by the activity multiplier inside the calculator.
RMR_MASS_COEFFICIENT_KCAL_PER_KG: Final[float] = 10.0

#: Sex-dependent additive constant of the Mifflin-St Jeor RMR equation, keyed by
#: the metabolic formula preference. The ``+5`` variant is the +5 kcal/day
#: constant; the ``-161`` variant is the -161 kcal/day constant.
MIFFLIN_HEIGHT_COEFFICIENT_KCAL_PER_CM: Final[float] = 6.25
MIFFLIN_AGE_COEFFICIENT_KCAL_PER_YEAR: Final[float] = 5.0
MIFFLIN_PLUS5_CONSTANT_KCAL: Final[float] = 5.0
MIFFLIN_MINUS161_CONSTANT_KCAL: Final[float] = -161.0

#: Safety floor on the daily calorie target, by formula variant. Targets below
#: these clinically conservative minimums for unsupervised dieting are refused
#: (clamped up to the floor and flagged), never returned as guidance. The
#: ``-161`` and ``+5`` variant minimums of 1200 and 1500 kcal/day are common
#: public-health guidance for medically unsupervised weight loss.
SAFETY_FLOOR_KCAL_PLUS5: Final[int] = 1500
SAFETY_FLOOR_KCAL_MINUS161: Final[int] = 1200

#: Safety ceiling on the daily calorie target. An implausibly aggressive weight
#: *gain* over a very short horizon would demand an enormous surplus; targets
#: above this conservative cap are clamped down and flagged rather than returned.
SAFETY_CEILING_KCAL: Final[int] = 4000

# --- Macro targets (FTY-094) -------------------------------------------------
#
# The three macro targets are derived from the safety-clamped daily calorie
# target in a fixed evidence-based order — protein first (anchored to
# bodyweight), then a fat floor, then carbohydrate as the non-negative
# remainder. Every default below is sourced; see docs/contracts/target-calculator.md.

#: Atwater energy factors — kcal per gram of each macronutrient. The familiar
#: 4/9/4 metabolizable-energy values; used to convert between grams and kcal.
KCAL_PER_G_PROTEIN: Final[int] = 4
KCAL_PER_G_CARB: Final[int] = 4
KCAL_PER_G_FAT: Final[int] = 9

#: Protein target, grams per kg of bodyweight per day. The largest meta-analysis
#: to date (Morton et al., *Br J Sports Med* 2018) identifies ~1.6 g/kg/day as
#: the breakpoint beyond which added protein yields no further lean-mass benefit;
#: systematic reviews of hypocaloric diets in adults with overweight/obesity find
#: 1.2–1.6 g/kg/day optimal for fat loss with lean-mass preservation. 1.6 g/kg
#: sits at the top of that protective band and at the muscle-protein-synthesis
#: ceiling — a strong, simple, total-bodyweight-anchored default. Anchored to
#: *current/start* bodyweight (not the lower goal weight): in a deficit you anchor
#: to current mass to protect lean tissue. Total-bodyweight scaling slightly
#: overestimates need at high adiposity (lean-mass-based anchoring is more
#: precise) — a known refinement, not a v1 blocker.
PROTEIN_G_PER_KG: Final[float] = 1.6

#: Fat target as a share of the daily calorie target. The Dietary Guidelines for
#: Americans place fat at 20–35% of energy; 30% is a calm evidence-based midpoint.
FAT_PCT_OF_CALORIES: Final[float] = 0.30

#: Hormonal-health floor on fat, grams per kg of bodyweight per day. Evidence
#: shows dropping below ~20% of energy / ~0.8 g/kg lowers sex-hormone (e.g.
#: testosterone) levels; this floor guarantees enough fat for essential fatty
#: acids / sex-hormone health when a deep deficit would otherwise push the
#: percentage share too low.
FAT_FLOOR_G_PER_KG: Final[float] = 0.8
