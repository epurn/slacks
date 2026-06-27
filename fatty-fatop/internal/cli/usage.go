package cli

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/epurn/fatty-fatop/internal/config"
	"github.com/epurn/fatty-fatop/internal/state"
	"github.com/epurn/fatty-fatop/internal/ui"
)

// runUsage renders token + cost accounting aggregated from run_usage /
// review_usage events. Read-only: it never touches anything but the event logs.
func runUsage(args []string) int {
	fs := flag.NewFlagSet("usage", flag.ContinueOnError)
	root := rootFlag(fs)
	since := fs.String("since", "today", "window: today | all | a duration like 24h, 90m")
	n := fs.Int("n", 15, "how many recent runs to list")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	paths := config.Resolve(*root)

	cutoff, label, err := parseSince(*since)
	if err != nil {
		fmt.Fprintln(os.Stderr, "usage:", err)
		return 2
	}

	// Usage envelopes are emitted at the service level by the author and reviewer.
	events := state.MergeEvents([]string{paths.AuthorEvents, paths.ReviewerEvents}, 0)
	records := state.CollectUsage(events)
	sum := state.SummarizeUsage(records, cutoff)

	fmt.Println(ui.Accent.Render("fatop usage") + ui.Muted.Render("  "+label))
	fmt.Println()

	if sum.Runs == 0 {
		fmt.Println(ui.Muted.Render("  no completed runs in this window"))
		return 0
	}

	// Totals
	fmt.Println(ui.Bold.Render("totals"))
	fmt.Printf("  runs        %d\n", sum.Runs)
	fmt.Printf("  cost        %s\n", ui.Bold.Render(fmtUSD(sum.CostUSD)))
	fmt.Printf("  avg/run     %s\n", fmtUSD(sum.AvgCostPerRun()))
	if br := sum.BurnRateUSDPerHour(); br > 0 {
		fmt.Printf("  burn rate   %s/h  %s\n", fmtUSD(br), ui.Muted.Render("over "+shortDur(sum.Span())))
	} else {
		fmt.Printf("  burn rate   %s\n", ui.Muted.Render("— (window too short)"))
	}
	fmt.Printf("  tokens      %s in · %s out · %s cache-read\n",
		fmtTokens(sum.InputTokens+sum.CacheCreateTokens), fmtTokens(sum.OutputTokens), fmtTokens(sum.CacheReadTokens))
	fmt.Printf("  cache hit   %s %s\n", pct(sum.CacheHitRatio()), ui.Muted.Render("of input served from cache"))
	fmt.Printf("  turns       %d\n", sum.Turns)
	fmt.Println()

	// Per-model
	fmt.Println(ui.Bold.Render("by model"))
	fmt.Printf("  %-10s %5s  %10s  %9s  %9s  %6s\n",
		ui.Muted.Render("model"), ui.Muted.Render("runs"), ui.Muted.Render("cost"),
		ui.Muted.Render("in"), ui.Muted.Render("out"), ui.Muted.Render("turns"))
	for _, m := range sum.ModelsByCost() {
		fmt.Printf("  %-10s %5d  %10s  %9s  %9s  %6d\n",
			m.Model, m.Runs, fmtUSD(m.CostUSD), fmtTokens(m.InputTokens), fmtTokens(m.OutputTokens), m.Turns)
	}
	fmt.Println()

	// Recent runs
	fmt.Println(ui.Bold.Render("recent runs"))
	recs := sum.Records
	if *n > 0 && len(recs) > *n {
		recs = recs[len(recs)-*n:]
	}
	for i := len(recs) - 1; i >= 0; i-- {
		r := recs[i]
		ts := "--:--:--"
		if !r.Ts.IsZero() {
			ts = r.Ts.Local().Format("01-02 15:04")
		}
		mode := r.Mode
		if mode == "" {
			mode = "review"
		}
		fmt.Printf("  %s  %-8s %-8s %-8s %5dt  %8s  %s\n",
			ui.Muted.Render(ts),
			ui.Run.Render(r.RunID),
			r.Model,
			ui.Muted.Render(mode),
			r.Turns,
			ui.Bold.Render(fmtUSD(r.CostUSD)),
			ui.Muted.Render(fmtTokens(r.OutputTokens)+" out · "+pct(r.CacheHitRatio())+" cache"))
	}
	return 0
}

// parseSince resolves a window spec into a cutoff time (zero = no cutoff) and a
// human label for the header.
func parseSince(spec string) (time.Time, string, error) {
	switch strings.ToLower(strings.TrimSpace(spec)) {
	case "", "today":
		now := time.Now()
		start := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
		return start, "today", nil
	case "all":
		return time.Time{}, "all time", nil
	default:
		d, err := time.ParseDuration(spec)
		if err != nil {
			return time.Time{}, "", fmt.Errorf("bad --since %q (use today, all, or a duration like 24h)", spec)
		}
		return time.Now().Add(-d), "last " + spec, nil
	}
}

// fmtUSD renders a dollar amount with cent precision, or sub-cent for tiny runs.
func fmtUSD(v float64) string {
	if v == 0 {
		return "$0.00"
	}
	if v < 0.01 {
		return fmt.Sprintf("$%.4f", v)
	}
	return fmt.Sprintf("$%.2f", v)
}

// fmtTokens renders a token count compactly: 812, 3.4k, 6.3M.
func fmtTokens(n int64) string {
	switch {
	case n < 1000:
		return fmt.Sprintf("%d", n)
	case n < 1_000_000:
		return fmt.Sprintf("%.1fk", float64(n)/1000)
	default:
		return fmt.Sprintf("%.1fM", float64(n)/1_000_000)
	}
}

// pct renders a 0..1 ratio as a whole-number percentage.
func pct(r float64) string {
	return fmt.Sprintf("%.0f%%", r*100)
}
