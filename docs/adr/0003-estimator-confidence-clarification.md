# ADR 0003: Estimator Confidence & Clarification Architecture

## Status

Accepted. Decided 2026-07-01.

Phase 1 (Layer A, estimate-first prompting, and the measurement harness) is
**shipped**. Phase 2's Layer B self-consistency signal is **shipped** (FTY-158)
as an offline-validated signal — not yet wired into the live gate. Naturalistic
calibration data (FTY-169) and Layer C (FTY-159) remain **queued** — see
Consequences.

This ADR supersedes the internal command-centre research doc that originally
explored this problem as the decision of record for this architecture — that
doc was planning history; this ADR is the durable, public reasoning, recorded
where the code it governs lives.

## Context

The NL-parse step (`docs/contracts/parse-candidates.md`) routes a parsed entry
to completion or to a clarifying question. That routing decision — "estimate
this" versus "ask the user for a detail" — was driven by a single signal: an
**LLM self-reported `confidence ∈ [0, 1]`**, compared against a hardcoded
threshold (`PARSE_CONFIDENCE_CLARIFY_THRESHOLD = 0.45` in
`backend/app/estimator/parse.py`, with a parallel
`LABEL_CONFIDENCE_CLARIFY_THRESHOLD = 0.5` on the nutrition-label path in
`label_step.py`).

Dogfooding surfaced two failures with this design:

1. **It over-asked.** The clarify gate fired on entries a human — or the model
   itself, if prompted differently — could plainly estimate ("3 PB cracker
   sandwiches" implies roughly 6 crackers and ~1 tbsp of peanut butter each).
   Every unnecessary clarifying question costs a log and works against the
   habit the product depends on.
2. **The signal and the threshold backing it are individually weak**, on two
   independent counts:
   - **Verbalized confidence is poorly calibrated on RLHF/instruct models**,
     and systematically overconfident. The OpenAI GPT-4 Technical Report
     (2023, arXiv:2303.08774) reports expected calibration error rising from
     ~0.007 pre-RLHF to ~0.074 post-RLHF on the same model family. Xiong et
     al. (ICLR 2024, arXiv:2306.13063) and Tian et al. (EMNLP 2023,
     arXiv:2305.14975) independently confirm verbalized confidence is a weak,
     overconfident signal on instruction-tuned LLMs.
   - **A fixed threshold is fragile under distribution shift.** `0.45` was an
     unprincipled guess, not a calibrated operating point. Kamath, Jia & Liang
     (ACL 2020) show a trained selective-answering calibrator reaches 56%
     coverage at 80% accuracy versus 48% for a raw-score threshold on the same
     task — a fixed cutoff picked without calibration data leaves real
     accuracy on the table.

**The load-bearing constraint: Slacks' plan-covered provider is Claude.**
Slacks runs LLM calls through the `claude_code` subscription provider
(`docs/architecture/system-overview.md`), and the **Anthropic Messages API
exposes no token log-probabilities**. This rules out the standard
logprob-based confidence estimators (e.g. mean token log-probability,
predictive entropy) used in most confidence-calibration literature — they are
not computable against Slacks' primary provider. The signals that remain
viable are:

- **verbalized confidence** — available, but weak (see above);
- **self-consistency / sampling agreement** — black-box (needs only repeated
  completions, not logprobs), and works against Claude;
- **deterministic external validation** — model-free, needs no provider
  cooperation at all.

## Decision

Adopt a **layered clarify-gate architecture** that replaces reliance on a bare
verbalized-confidence threshold with deterministic validation, estimate-first
prompting, and (in later phases) a black-box statistical signal calibrated
against real data — instead of one uncalibrated self-reported number compared
to a guessed constant.

### Layer A — deterministic plausibility validators (shipped, FTY-156)

A cheap, model-free external oracle (`backend/app/estimator/plausibility.py`,
`check_candidate`) checks each parsed **food** candidate's quantity against
coarse physical/serving sanity ranges (plausible count, mass, and volume
bounds, and a food-specific unit vocabulary) before a parse is trusted, no
matter what confidence the model reported. A single implausible candidate
routes the whole event to `needs_clarification` with a targeted question. This
catches parses no verbalized-confidence score can be trusted to catch, because
it does not depend on the model self-assessing at all. See
`docs/contracts/clarify-gates.md` ("Deterministic plausibility gate") for
the exact bounds and rationale.

### Cross-cutting — estimate-first prompting (shipped, FTY-155 + FTY-167)

The parse prompt infers the typical portion, count, or composition a casual
description implies, rather than reflexively asking when a quantity is
unstated ("3 PB cracker sandwiches" → 6 crackers + ~1 tbsp peanut butter each).
Low confidence is reserved for input that is *genuinely* indeterminate, not
merely unstated. FTY-167 extended this into the deterministic calculator
layers for detail-rich casual entries — counts, ranges, servings, distances,
step counts, and game counts all route to estimation instead of clarification
when the underlying detail signal is present
(`backend/app/estimator/detail_signals.py`;
see `docs/contracts/parse-candidates.md`, "Detail-signal routing override").
This is prompting and deterministic routing, not a change to the confidence
signal itself, and it is cross-cutting: it works whether the ultimate operating
signal is verbalized confidence (today) or self-consistency (Layer B).

### Measurement harness (shipped, FTY-157)

A labeled evaluation set plus a risk-coverage / over-ask / under-ask scorer,
so any change to the clarify gate — prompt, layer, or threshold — can be
measured against a fixed standard rather than judged by anecdote. This harness
is what phases 2–3 calibrate against.

### Layer B — self-consistency signal (shipped, FTY-158, phase 2)

Sample the parse step N≈3 times in parallel and measure agreement across the
parsed items and quantities, hybridized with the verbalized score into a
single operating signal. This is black-box — it needs only repeated
completions, not logprobs — so it works against Claude where logprob-based
estimators cannot. It follows the self-consistency line of work established
for hallucination/confidence detection without model internals (Manakul et
al., EMNLP 2023, SelfCheckGPT).

Shipped as `backend/app/estimator/self_consistency.py`: a pairwise
item/quantity concordance metric over N=3 parallel samples with a
unanimous-first-window early stop (window 2 — easy inputs pay one extra sample,
contested inputs pay the full N), hybridized with the verbalized mean at
agreement weight 0.6 (chosen so total disagreement stays below the 0.45
operating threshold even at verbalized confidence 1.0 — fail closed). Measured
on the FTY-157 set: 94.7% correct decisions for the hybrid (93.7%
agreement-only) versus 85.3% for the verbalized baseline at the 0.45 operating
point, with over-ask 11.5% → 3.5% and under-ask 21% → 9%
(`tests/fixtures/parse_calibration/self_consistency_summary.json`). The signal
is **not yet wired into the live gate** — that bake-off and threshold
calibration is Layer C (FTY-159).

### Naturalistic calibration data (queued, FTY-169, phase 2)

Verbalized confidence and self-consistency both need calibration data to set a
real operating point, and synthetic examples alone risk overfitting the gate
to how a test set was written rather than how users actually write. FTY-169
builds a naturalistic set of messy, real-world-style descriptions labeled by a
**cross-provider judge**: Claude and GPT-5.5 each label an example
independently; agreement is accepted as the label, and disagreement routes to
a small human-adjudication queue. Judging with two independent model families
breaks the circularity of a model grading its own outputs.

### Layer C — data-calibrated threshold (queued, FTY-159, phase 3)

Calibrate the operating point of the winning signal (Layer B, hybridized with
verbalized confidence, or verbalized confidence alone if Layer B does not
outperform it) using risk-coverage curves over the synthetic and naturalistic
sets, in the spirit of Guo et al. (ICML 2017, temperature scaling), Yadkori et
al. (2024, conformal abstention), and Li et al. (ICLR 2024, early-stopping
self-consistency). This replaces the hardcoded `0.45` / `0.5` constants with a
calibrated policy backed by measured accuracy at that operating point, rather
than a guess.

### Product stance this architecture serves

This architecture exists to serve two already-committed product design
principles:

- **"Estimate first, ask only when truly stuck."** An estimate rendered with
  visible provenance and easy one-tap correction is not fabrication; a
  reflexive clarifying question for something any human could infer is pure
  friction against the logging habit the product depends on.
- **"Every number shows where it came from."** Trust is preserved by showing
  the user where an estimate came from and inviting correction — not by
  refusing to estimate, and not by an internal confidence score the user never
  sees. The clarify gate's job is to catch cases that are *genuinely*
  indeterminate, not to hide behind caution.

Zhang & Choi (Findings of NAACL 2025) further note that instruction-tuned
models rarely volunteer a clarifying question on their own even when one is
warranted — reinforcing that the routing decision belongs in engineered policy
(this architecture), not left to the model's own judgment about when to ask.

## Consequences

- **Cost and latency.** Layer B's self-consistency sampling costs roughly N×
  the tokens of a single parse call. Latency stays close to flat because the N
  samples run in parallel, not sequentially.
- **Fail-closed invariant preserved.** Every layer in this architecture
  tightens or replaces the *signal* feeding the clarify decision; none of them
  change the routing invariant that ambiguous or invalid output clarifies or
  fails closed rather than guessing silently (`docs/contracts/parse-candidates.md`,
  "Validation").
- **The operating point is not permanent.** Any threshold Layer C calibrates
  is a function of the current prompt and model. A prompt rewrite or model
  change invalidates the calibration and requires re-tuning against the
  measurement harness (FTY-157) before the new threshold can be trusted.
- **No contract or schema change from this ADR.** `ParseResult` and the parse
  routing table in `docs/contracts/parse-candidates.md` are unchanged by this
  decision; Layer C's threshold swap, when it lands (FTY-159), is a tunable
  constant change, not a schema change.
- **Sequencing.** Phase 1 (this ADR's shipped layers) already improved the
  over-ask rate without waiting on phases 2–3. FTY-158 and FTY-169 are
  independent of each other and can run in parallel; FTY-159 depends on
  whichever of them the measurement harness shows is worth calibrating.

## Citations

1. Xiong et al., "Can LLMs Express Their Uncertainty? An Empirical Evaluation
   of Confidence Elicitation in LLMs," ICLR 2024, arXiv:2306.13063.
2. Tian et al., "Just Ask for Calibration: Strategies for Eliciting Calibrated
   Confidence Scores from Language Models Fine-Tuned with Human Feedback,"
   EMNLP 2023, arXiv:2305.14975.
3. OpenAI, "GPT-4 Technical Report," 2023, arXiv:2303.08774.
4. Kamath, Jia & Liang, "Selective Question Answering under Domain Shift,"
   ACL 2020.
5. Manakul, Liusie & Gales, "SelfCheckGPT: Zero-Resource Black-Box Hallucination
   Detection for Generative Large Language Models," EMNLP 2023.
6. Guo, Pleiss, Sun & Weinberger, "On Calibration of Modern Neural Networks,"
   ICML 2017.
7. Yadkori, Kuzborskij, György & Szepesvári, "To Believe or Not to Believe
   Your LLM," 2024.
8. Li et al., "Escape Sky-high Cost: Early-Stopping Self-Consistency for
   Multi-Step Reasoning," ICLR 2024, arXiv:2401.10480.
9. Zhang & Choi, "Clarify When Necessary: Resolving Ambiguity Through
   Interaction with LMs," Findings of NAACL 2025, arXiv:2311.09469.
