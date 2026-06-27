package state

import (
	"sort"
	"time"
)

// UsageRecord is one completed run's token + cost accounting, derived from a
// run_usage (author) or review_usage (reviewer) event. See
// docs/agent-event-log.md for the source fields.
type UsageRecord struct {
	Ts          time.Time
	Agent       string // author | reviewer
	RunID       string // FTY-020, PR-14, ...
	Model       string // resolved model, e.g. opus
	Mode        string // implement | fix-pr | publish; empty for reviewer

	InputTokens       int64 // fresh prompt tokens
	OutputTokens      int64
	CacheCreateTokens int64 // cache_creation_input_tokens
	CacheReadTokens   int64 // cache_read_input_tokens

	CostUSD float64
	Turns   int
}

// TotalInputTokens is everything billed on the input side: fresh prompt plus
// both cache halves. Cache reads are the cheap majority on long runs.
func (u UsageRecord) TotalInputTokens() int64 {
	return u.InputTokens + u.CacheCreateTokens + u.CacheReadTokens
}

// CacheHitRatio is the fraction of input tokens served from cache (0..1). This
// is the single biggest cost lever, so it is surfaced prominently.
func (u UsageRecord) CacheHitRatio() float64 {
	in := u.TotalInputTokens()
	if in == 0 {
		return 0
	}
	return float64(u.CacheReadTokens) / float64(in)
}

// usageEvents are the event types that carry a full usage payload.
func isUsageEvent(eventType string) bool {
	return eventType == "run_usage" || eventType == "review_usage"
}

// UsageFromEvent extracts a UsageRecord from a run_usage / review_usage event.
// ok is false for any other event type.
func UsageFromEvent(e Event) (UsageRecord, bool) {
	if !isUsageEvent(e.EventT) {
		return UsageRecord{}, false
	}
	rec := UsageRecord{
		Ts:    e.Ts,
		Agent: e.Agent,
		RunID: e.RunID,
		Model: e.Field("model"),
		Mode:  e.Field("mode"),
	}
	rec.InputTokens, _ = e.FieldInt("input_tokens")
	rec.OutputTokens, _ = e.FieldInt("output_tokens")
	rec.CacheCreateTokens, _ = e.FieldInt("cache_creation_input_tokens")
	rec.CacheReadTokens, _ = e.FieldInt("cache_read_input_tokens")
	if c, ok := e.FieldFloat("total_cost_usd"); ok {
		rec.CostUSD = c
	}
	if t, ok := e.FieldInt("num_turns"); ok {
		rec.Turns = int(t)
	}
	return rec, true
}

// CollectUsage pulls every usage record out of a slice of events, oldest first.
func CollectUsage(events []Event) []UsageRecord {
	var out []UsageRecord
	for _, e := range events {
		if rec, ok := UsageFromEvent(e); ok {
			out = append(out, rec)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Ts.Before(out[j].Ts) })
	return out
}

// ModelUsage is the per-model rollup inside a UsageSummary.
type ModelUsage struct {
	Model        string
	Runs         int
	CostUSD      float64
	InputTokens  int64
	OutputTokens int64
	Turns        int
}

// UsageSummary aggregates a set of UsageRecords for a window (e.g. today, or the
// whole stream).
type UsageSummary struct {
	Records []UsageRecord

	Runs              int
	CostUSD           float64
	InputTokens       int64
	OutputTokens      int64
	CacheCreateTokens int64
	CacheReadTokens   int64
	Turns             int

	ByModel map[string]*ModelUsage // keyed by model name

	First time.Time // earliest record ts
	Last  time.Time // latest record ts
}

// TotalInputTokens mirrors UsageRecord across the whole window.
func (s UsageSummary) TotalInputTokens() int64 {
	return s.InputTokens + s.CacheCreateTokens + s.CacheReadTokens
}

// CacheHitRatio is the windowed fraction of input tokens served from cache.
func (s UsageSummary) CacheHitRatio() float64 {
	in := s.TotalInputTokens()
	if in == 0 {
		return 0
	}
	return float64(s.CacheReadTokens) / float64(in)
}

// Span is the wall-clock time between the first and last record in the window.
func (s UsageSummary) Span() time.Duration {
	if s.First.IsZero() || s.Last.IsZero() || !s.Last.After(s.First) {
		return 0
	}
	return s.Last.Sub(s.First)
}

// BurnRateUSDPerHour is windowed spend divided by the span. Returns 0 when the
// span is too small to be meaningful (single run, or sub-minute window), so
// callers can show "—" rather than a wildly inflated rate.
func (s UsageSummary) BurnRateUSDPerHour() float64 {
	span := s.Span()
	if span < time.Minute {
		return 0
	}
	return s.CostUSD / span.Hours()
}

// AvgCostPerRun is the mean cost across runs in the window.
func (s UsageSummary) AvgCostPerRun() float64 {
	if s.Runs == 0 {
		return 0
	}
	return s.CostUSD / float64(s.Runs)
}

// ModelsByCost returns the per-model rollups sorted by spend, descending.
func (s UsageSummary) ModelsByCost() []ModelUsage {
	out := make([]ModelUsage, 0, len(s.ByModel))
	for _, m := range s.ByModel {
		out = append(out, *m)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].CostUSD > out[j].CostUSD })
	return out
}

// SummarizeUsage rolls up records whose timestamp is at or after `since` (pass
// the zero time for "all"). Records are retained in the summary, oldest first.
func SummarizeUsage(records []UsageRecord, since time.Time) UsageSummary {
	s := UsageSummary{ByModel: map[string]*ModelUsage{}}
	for _, r := range records {
		if !since.IsZero() && r.Ts.Before(since) {
			continue
		}
		s.Records = append(s.Records, r)
		s.Runs++
		s.CostUSD += r.CostUSD
		s.InputTokens += r.InputTokens
		s.OutputTokens += r.OutputTokens
		s.CacheCreateTokens += r.CacheCreateTokens
		s.CacheReadTokens += r.CacheReadTokens
		s.Turns += r.Turns

		if s.First.IsZero() || r.Ts.Before(s.First) {
			s.First = r.Ts
		}
		if r.Ts.After(s.Last) {
			s.Last = r.Ts
		}

		model := r.Model
		if model == "" {
			model = "unknown"
		}
		m := s.ByModel[model]
		if m == nil {
			m = &ModelUsage{Model: model}
			s.ByModel[model] = m
		}
		m.Runs++
		m.CostUSD += r.CostUSD
		m.InputTokens += r.InputTokens
		m.OutputTokens += r.OutputTokens
		m.Turns += r.Turns
	}
	return s
}
