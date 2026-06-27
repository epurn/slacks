package cli

import (
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/epurn/fatty-fatop/internal/config"
	"github.com/epurn/fatty-fatop/internal/state"
	"github.com/epurn/fatty-fatop/internal/ui"
)

// runQueue prints the steward's story queue in assignment order, plus open PRs,
// so the order and review state are visible without leaving the tool. Read-only.
func runQueue(args []string) int {
	fs := flag.NewFlagSet("queue", flag.ContinueOnError)
	root := rootFlag(fs)
	if err := fs.Parse(args); err != nil {
		return 2
	}
	paths := config.Resolve(*root)

	queue, err := state.LoadQueue(paths.Roadmap, paths.StoriesDir, paths.RunDir)
	if err != nil {
		fmt.Fprintln(os.Stderr, "queue:", err)
		return 1
	}

	fmt.Println(ui.Accent.Render("fatop queue") + ui.Muted.Render("  "+paths.Roadmap))
	fmt.Println()

	// Split into what the steward can do now vs what is held back.
	var assignable, blocked, tripped []state.QueueStory
	for _, q := range queue {
		switch {
		case q.Tripped():
			tripped = append(tripped, q)
		case q.Active:
			assignable = append(assignable, q) // running shows in the ready group
		case q.Blocked():
			blocked = append(blocked, q)
		default:
			assignable = append(assignable, q)
		}
	}

	fmt.Println(ui.Bold.Render("ready — in assignment order"))
	if len(assignable) == 0 {
		fmt.Println(ui.Muted.Render("  none assignable"))
	}
	for i, q := range assignable {
		fmt.Printf("  %2d. %s\n", i+1, queueLine(q))
	}
	fmt.Println()

	if len(blocked) > 0 {
		fmt.Println(ui.Bold.Render("blocked — waiting on dependencies"))
		for _, q := range blocked {
			fmt.Printf("      %s\n", queueLine(q))
		}
		fmt.Println()
	}

	if len(tripped) > 0 {
		fmt.Println(ui.Bold.Render("needs attention — circuit breaker / pulled"))
		for _, q := range tripped {
			fmt.Printf("      %s\n", queueLine(q))
		}
		fmt.Println()
	}

	// Open PRs, so the user can review them and see their state here too.
	fmt.Println(ui.Bold.Render("open PRs"))
	prs, err := state.LoadPRs(paths.Repo)
	if err != nil {
		fmt.Println(ui.Warn.Render("  gh unavailable: " + err.Error()))
	} else if len(prs) == 0 {
		fmt.Println(ui.Muted.Render("  none"))
	} else {
		for _, pr := range prs {
			fmt.Printf("  #%-4d %s %s %s\n", pr.Number, reviewBadge(pr), checksBadge(pr), truncate(pr.Title, 56))
		}
	}
	return 0
}

// queueLine renders one story row: id, lane, badges, title.
func queueLine(q state.QueueStory) string {
	var badge string
	switch {
	case q.Active:
		badge = ui.Run.Render("running")
	case q.Tripped():
		badge = ui.Err.Render("attention")
	case q.Blocked():
		badge = ui.Warn.Render("blocked")
	default:
		badge = ui.OK.Render("ready")
	}
	id := ui.Bold.Render(fmt.Sprintf("%-8s", q.ID))
	lane := ui.Muted.Render(fmt.Sprintf("%-15s", q.Lane))
	extra := ""
	if len(q.UnmetDeps) > 0 {
		extra += ui.Warn.Render(" ⟂ " + strings.Join(q.UnmetDeps, ","))
	}
	if q.Attempts > 0 {
		extra += ui.Muted.Render(fmt.Sprintf("  %d attempts", q.Attempts))
	}
	state := ui.Muted.Render(q.State)
	return fmt.Sprintf("%s %-9s %s %s  %s%s", id, badge, lane, state, truncate(q.Title, 40), extra)
}
