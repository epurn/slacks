package state

import (
	"testing"
	"time"
)

func mkUsageEvent(ts, agent, runID, event, model, mode string, in, out, cacheCreate, cacheRead int64, cost float64, turns int) Event {
	e := Event{
		Agent:  agent,
		RunID:  runID,
		EventT: event,
		Fields: map[string]any{
			"model":                       model,
			"input_tokens":                float64(in),
			"output_tokens":               float64(out),
			"cache_creation_input_tokens": float64(cacheCreate),
			"cache_read_input_tokens":     float64(cacheRead),
			"total_cost_usd":              cost,
			"num_turns":                   float64(turns),
		},
	}
	if mode != "" {
		e.Fields["mode"] = mode
	}
	if t, err := time.Parse(time.RFC3339, ts); err == nil {
		e.Ts = t
	}
	return e
}

func TestUsageFromEvent(t *testing.T) {
	e := mkUsageEvent("2026-06-26T16:28:22Z", "author", "FTY-020", "run_usage", "opus", "implement",
		14816, 69852, 155633, 6263180, 6.57, 100)
	rec, ok := UsageFromEvent(e)
	if !ok {
		t.Fatal("expected run_usage to parse")
	}
	if rec.Model != "opus" || rec.Mode != "implement" {
		t.Errorf("model/mode = %q/%q", rec.Model, rec.Mode)
	}
	if rec.OutputTokens != 69852 || rec.Turns != 100 {
		t.Errorf("output/turns = %d/%d", rec.OutputTokens, rec.Turns)
	}
	if rec.CostUSD != 6.57 {
		t.Errorf("cost = %v", rec.CostUSD)
	}
	// 6263180 / (14816 + 155633 + 6263180) = ~0.974
	if r := rec.CacheHitRatio(); r < 0.97 || r > 0.98 {
		t.Errorf("cache hit ratio = %v, want ~0.974", r)
	}

	if _, ok := UsageFromEvent(Event{EventT: "poll_cycle"}); ok {
		t.Error("poll_cycle should not parse as usage")
	}
}

func TestSummarizeUsageWindowAndModels(t *testing.T) {
	recs := CollectUsage([]Event{
		mkUsageEvent("2026-06-26T10:00:00Z", "author", "FTY-001", "run_usage", "opus", "implement", 1000, 2000, 500, 8000, 4.00, 80),
		mkUsageEvent("2026-06-26T11:00:00Z", "reviewer", "PR-9", "review_usage", "sonnet", "", 100, 300, 50, 900, 0.40, 10),
		// before the cutoff — must be excluded
		mkUsageEvent("2026-06-25T10:00:00Z", "author", "FTY-000", "run_usage", "opus", "implement", 1, 1, 1, 1, 99.0, 1),
	})
	if len(recs) != 3 {
		t.Fatalf("collected %d records, want 3", len(recs))
	}

	cutoff, _ := time.Parse(time.RFC3339, "2026-06-26T00:00:00Z")
	s := SummarizeUsage(recs, cutoff)
	if s.Runs != 2 {
		t.Fatalf("runs = %d, want 2 (cutoff should drop the old one)", s.Runs)
	}
	if s.CostUSD != 4.40 {
		t.Errorf("cost = %v, want 4.40", s.CostUSD)
	}
	if s.Turns != 90 {
		t.Errorf("turns = %d, want 90", s.Turns)
	}
	// Span is 1h, cost 4.40 → 4.40/h.
	if br := s.BurnRateUSDPerHour(); br < 4.39 || br > 4.41 {
		t.Errorf("burn rate = %v, want ~4.40/h", br)
	}
	models := s.ModelsByCost()
	if len(models) != 2 || models[0].Model != "opus" {
		t.Fatalf("models by cost = %+v, want opus first", models)
	}
	if models[0].Runs != 1 || models[0].CostUSD != 4.00 {
		t.Errorf("opus rollup = %+v", models[0])
	}
}

func TestBurnRateZeroForShortWindow(t *testing.T) {
	recs := CollectUsage([]Event{
		mkUsageEvent("2026-06-26T10:00:00Z", "author", "FTY-001", "run_usage", "opus", "implement", 1, 1, 1, 1, 5.0, 1),
	})
	s := SummarizeUsage(recs, time.Time{})
	if br := s.BurnRateUSDPerHour(); br != 0 {
		t.Errorf("single-run burn rate = %v, want 0 (span too short)", br)
	}
}
