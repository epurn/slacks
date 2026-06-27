// Package cli implements fatop's scriptable subcommands. The TUI lives behind
// `fatop watch` (and bare `fatop`); everything else here is one-shot, colorized,
// and pipe-friendly.
package cli

import (
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/epurn/fatty-fatop/internal/config"
	"github.com/epurn/fatty-fatop/internal/state"
	"github.com/epurn/fatty-fatop/internal/tui"
	"github.com/epurn/fatty-fatop/internal/ui"
)

const usage = `fatop — Fatty agent monitor

usage:
  fatop                      launch the live TUI dashboard
  fatop watch                same as bare fatop
  fatop status               one-shot snapshot of services, runs, and PRs
  fatop logs [agent]         merged event stream (agent: steward|reviewer|author)
  fatop usage                token + cost accounting (--since, -n)
  fatop inspect <id|PR-n>    full detail + timeline for one run
  fatop doctor               verify fatop can read every source
  fatop help                 show this help

common flags:
  --root DIR    command-centre root (default: $FATTY_HOME or autodetect)

logs flags:
  -f, --follow  keep printing new events
  --level L     minimum level: debug|info|warn|error (default: debug)
  --grep S      only events whose text/event contains S
  -n N          show the last N events first (default: 40)

usage flags:
  --since W     window: today (default) | all | a duration like 24h, 90m
  -n N          how many recent runs to list (default: 15)
`

// Execute parses os.Args and runs the requested subcommand. Returns an exit code.
func Execute() int {
	args := os.Args[1:]
	if len(args) == 0 {
		return runWatch(nil)
	}
	cmd := args[0]
	rest := args[1:]
	switch cmd {
	case "help", "-h", "--help":
		fmt.Print(usage)
		return 0
	case "watch":
		return runWatch(rest)
	case "status":
		return runStatus(rest)
	case "logs":
		return runLogs(rest)
	case "usage":
		return runUsage(rest)
	case "inspect":
		return runInspect(rest)
	case "doctor":
		return runDoctor(rest)
	default:
		// Allow `fatop --root X` with no subcommand to launch the TUI.
		if strings.HasPrefix(cmd, "-") {
			return runWatch(args)
		}
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", cmd, usage)
		return 2
	}
}

func rootFlag(fs *flag.FlagSet) *string {
	return fs.String("root", "", "command-centre root")
}

func runWatch(args []string) int {
	fs := flag.NewFlagSet("watch", flag.ContinueOnError)
	root := rootFlag(fs)
	if err := fs.Parse(args); err != nil {
		return 2
	}
	paths := config.Resolve(*root)
	if err := tui.Run(paths); err != nil {
		fmt.Fprintln(os.Stderr, "fatop:", err)
		return 1
	}
	return 0
}

func runStatus(args []string) int {
	fs := flag.NewFlagSet("status", flag.ContinueOnError)
	root := rootFlag(fs)
	if err := fs.Parse(args); err != nil {
		return 2
	}
	paths := config.Resolve(*root)

	fmt.Println(ui.Accent.Render("fatop status") + ui.Muted.Render("  "+paths.Root))
	fmt.Println()

	// Services
	fmt.Println(ui.Bold.Render("services"))
	for _, s := range state.LoadServices() {
		fmt.Printf("  %s %-9s %s\n", ui.Dot(s.Up), s.Name, ui.Muted.Render(s.Detail))
	}
	fmt.Println()

	// Runs
	runs, _ := state.LoadRuns(paths.RunDir)
	fmt.Println(ui.Bold.Render("runs in flight"))
	if len(runs) == 0 {
		fmt.Println(ui.Muted.Render("  none"))
	}
	for _, r := range runs {
		marker := ui.Muted.Render("idle")
		if r.Active {
			marker = ui.Run.Render(fmt.Sprintf("running %s", shortDur(r.Age())))
		}
		lanes := strings.Join(r.Lanes, ",")
		fmt.Printf("  %-12s %-9s %-22s %s\n", ui.Bold.Render(r.ID), r.Mode, ui.Muted.Render(lanes), marker)
	}
	fmt.Println()

	// PRs
	fmt.Println(ui.Bold.Render("open PRs"))
	prs, err := state.LoadPRs(paths.Repo)
	if err != nil {
		fmt.Println(ui.Warn.Render("  gh unavailable: " + err.Error()))
	} else if len(prs) == 0 {
		fmt.Println(ui.Muted.Render("  none"))
	} else {
		for _, pr := range prs {
			fmt.Printf("  #%-4d %s %s %s\n", pr.Number, reviewBadge(pr), checksBadge(pr), truncate(pr.Title, 60))
		}
	}
	return 0
}

func runLogs(args []string) int {
	fs := flag.NewFlagSet("logs", flag.ContinueOnError)
	root := rootFlag(fs)
	follow := fs.Bool("follow", false, "keep printing new events")
	fs.BoolVar(follow, "f", false, "keep printing new events")
	level := fs.String("level", "debug", "minimum level")
	grep := fs.String("grep", "", "substring filter")
	n := fs.Int("n", 40, "show the last N events first")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	paths := config.Resolve(*root)

	var agent string
	if fs.NArg() > 0 {
		agent = fs.Arg(0)
	}
	sources := logSources(paths, agent)
	if len(sources) == 0 {
		fmt.Fprintln(os.Stderr, "unknown agent:", agent)
		return 2
	}

	minLevel := levelRank(*level)
	printed := map[string]bool{}

	emit := func(evs []state.Event) {
		for _, e := range evs {
			if levelRank(e.Level) < minLevel {
				continue
			}
			if *grep != "" && !matches(e, *grep) {
				continue
			}
			key := e.TsRaw + "|" + e.Agent + "|" + e.EventT + "|" + e.Msg
			if printed[key] {
				continue
			}
			printed[key] = true
			fmt.Println(formatEventLine(e))
		}
	}

	emit(state.MergeEvents(sources, *n))
	if !*follow {
		return 0
	}
	for {
		time.Sleep(1 * time.Second)
		emit(state.MergeEvents(sources, 0))
	}
}

func runInspect(args []string) int {
	fs := flag.NewFlagSet("inspect", flag.ContinueOnError)
	root := rootFlag(fs)
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if fs.NArg() == 0 {
		fmt.Fprintln(os.Stderr, "inspect needs a run id (e.g. FTY-010 or PR-6)")
		return 2
	}
	id := fs.Arg(0)
	paths := config.Resolve(*root)

	runs, _ := state.LoadRuns(paths.RunDir)
	var run *state.Run
	for i := range runs {
		if strings.EqualFold(runs[i].ID, id) {
			run = &runs[i]
			break
		}
	}
	if run == nil {
		fmt.Fprintf(os.Stderr, "no run found for %q in %s\n", id, paths.RunDir)
		return 1
	}

	fmt.Println(ui.Accent.Render("run " + run.ID))
	status := ui.Muted.Render("idle")
	if run.Active {
		status = ui.Run.Render("running " + shortDur(run.Age()))
	}
	fmt.Printf("  mode      %s\n", run.Mode)
	fmt.Printf("  status    %s\n", status)
	if run.Story != "" {
		fmt.Printf("  story     %s\n", run.Story)
	}
	if len(run.Lanes) > 0 {
		fmt.Printf("  lanes     %s\n", strings.Join(run.Lanes, ", "))
	}
	if run.Worktree != "" {
		fmt.Printf("  worktree  %s\n", ui.Muted.Render(run.Worktree))
	}
	fmt.Println()

	fmt.Println(ui.Bold.Render("timeline"))
	evs := state.MergeEvents([]string{run.EventsPath, paths.StewardEvents, paths.ReviewerEvents, paths.AuthorEvents}, 0)
	shown := 0
	for _, e := range evs {
		if e.RunID != run.ID {
			continue
		}
		fmt.Println("  " + formatEventLine(e))
		shown++
	}
	if shown == 0 {
		fmt.Println(ui.Muted.Render("  no structured events recorded yet"))
	}
	return 0
}

func runDoctor(args []string) int {
	fs := flag.NewFlagSet("doctor", flag.ContinueOnError)
	root := rootFlag(fs)
	if err := fs.Parse(args); err != nil {
		return 2
	}
	paths := config.Resolve(*root)
	ok := true
	fmt.Println(ui.Accent.Render("fatop doctor") + ui.Muted.Render("  "+paths.Root))

	check := func(label, path string, required bool) {
		_, err := os.Stat(path)
		switch {
		case err == nil:
			fmt.Printf("  %s %-16s %s\n", ui.OK.Render("ok"), label, ui.Muted.Render(path))
		case required:
			ok = false
			fmt.Printf("  %s %-16s %s\n", ui.Err.Render("missing"), label, ui.Muted.Render(path))
		default:
			fmt.Printf("  %s %-16s %s\n", ui.Muted.Render("absent"), label, ui.Muted.Render(path))
		}
	}
	check("run dir", paths.RunDir, true)
	check("steward log", paths.StewardLog, false)
	check("steward events", paths.StewardEvents, false)
	check("reviewer log", paths.ReviewerLog, false)
	check("reviewer events", paths.ReviewerEvents, false)
	check("author events", paths.AuthorEvents, false)

	if _, err := state.LoadPRs(paths.Repo); err != nil {
		fmt.Printf("  %s %-16s %s\n", ui.Warn.Render("warn"), "gh", err.Error())
	} else {
		fmt.Printf("  %s %-16s %s\n", ui.OK.Render("ok"), "gh", ui.Muted.Render(paths.Repo))
	}

	if !ok {
		return 1
	}
	return 0
}

// --- helpers ---

func logSources(p config.Paths, agent string) []string {
	switch agent {
	case "":
		return []string{p.StewardEvents, p.ReviewerEvents, p.AuthorEvents}
	case "steward", "reviewer", "author":
		return []string{p.AgentEvents(agent)}
	default:
		return nil
	}
}

func formatEventLine(e state.Event) string {
	ts := e.Ts.Local().Format("15:04:05")
	if e.Ts.IsZero() {
		ts = "--:--:--"
	}
	icon := ui.EventIcon(e.EventT, e.Field("kind"))
	st := ui.LevelStyle(e.Level)
	agent := ui.Accent.Render(fmt.Sprintf("%-8s", e.Agent))
	head := fmt.Sprintf("%s %s %s %s", ui.Muted.Render(ts), agent, icon, st.Render(e.EventT))
	msg := e.Msg
	if msg == "" {
		msg = inlineFields(e)
	}
	if e.RunID != "" && e.RunID != "service" {
		head += " " + ui.Run.Render("["+e.RunID+"]")
	}
	return head + "  " + msg
}

func inlineFields(e state.Event) string {
	keys := make([]string, 0, len(e.Fields))
	for k := range e.Fields {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, k+"="+e.Field(k))
	}
	return strings.Join(parts, " ")
}

func matches(e state.Event, sub string) bool {
	sub = strings.ToLower(sub)
	return strings.Contains(strings.ToLower(e.Msg), sub) ||
		strings.Contains(strings.ToLower(e.EventT), sub) ||
		strings.Contains(strings.ToLower(e.RunID), sub)
}

func levelRank(l string) int {
	switch l {
	case "debug":
		return 0
	case "info", "":
		return 1
	case "warn":
		return 2
	case "error":
		return 3
	}
	return 1
}

func reviewBadge(pr state.PR) string {
	switch pr.Review {
	case "APPROVED":
		return ui.OK.Render("approved")
	case "CHANGES_REQUESTED":
		return ui.Err.Render("changes-req")
	case "REVIEW_REQUIRED":
		return ui.Warn.Render("review-req")
	default:
		if pr.Draft {
			return ui.Muted.Render("draft")
		}
		return ui.Muted.Render("-")
	}
}

func checksBadge(pr state.PR) string {
	switch pr.Checks {
	case "SUCCESS":
		return ui.OK.Render("checks✓")
	case "FAILURE":
		return ui.Err.Render("checks✗")
	case "PENDING":
		return ui.Warn.Render("checks…")
	default:
		return ui.Muted.Render("checks?")
	}
}

func shortDur(d time.Duration) string {
	if d <= 0 {
		return "0s"
	}
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	if d < time.Hour {
		return fmt.Sprintf("%dm", int(d.Minutes()))
	}
	return fmt.Sprintf("%dh%dm", int(d.Hours()), int(d.Minutes())%60)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n <= 1 {
		return s[:n]
	}
	return s[:n-1] + "…"
}
