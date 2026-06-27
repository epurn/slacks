// Package tui implements the live fatop dashboard with Bubble Tea.
package tui

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/epurn/fatty-fatop/internal/config"
	"github.com/epurn/fatty-fatop/internal/state"
	"github.com/epurn/fatty-fatop/internal/ui"
)

// Run starts the TUI and blocks until the user quits.
func Run(paths config.Paths) error {
	m := newModel(paths)
	p := tea.NewProgram(m, tea.WithAltScreen())
	_, err := p.Run()
	return err
}

const refreshEvery = 2 * time.Second

// target is one selectable event source in the left rail.
type target struct {
	title     string
	meta      string
	sources   []string
	runFilter string
	active    bool
	level     string // running | blocked | idle | agent
}

type refreshMsg struct {
	services []state.Service
	runs     []state.Run
	prs      []state.PR
	prErr    error
	queue    []state.QueueStory
}

type tickMsg time.Time

type model struct {
	paths config.Paths

	width, height int
	ready         bool

	services []state.Service
	runs     []state.Run
	prs      []state.PR
	prErr    error
	queue    []state.QueueStory

	targets  []target
	selected int

	vp       viewport.Model
	follow   bool
	minLevel int
	showHelp bool

	updated time.Time
}

func newModel(paths config.Paths) model {
	return model{
		paths:    paths,
		follow:   true,
		minLevel: 1, // info
	}
}

func (m model) Init() tea.Cmd {
	return tea.Batch(m.refreshCmd(), tickCmd())
}

func (m model) refreshCmd() tea.Cmd {
	p := m.paths
	return func() tea.Msg {
		services := state.LoadServices()
		runs, _ := state.LoadRuns(p.RunDir)
		prs, prErr := state.LoadPRs(p.Repo)
		queue, _ := state.LoadQueue(p.Roadmap, p.StoriesDir, p.RunDir)
		return refreshMsg{services: services, runs: runs, prs: prs, prErr: prErr, queue: queue}
	}
}

func tickCmd() tea.Cmd {
	return tea.Tick(refreshEvery, func(t time.Time) tea.Msg { return tickMsg(t) })
}

func (m *model) buildTargets() {
	p := m.paths
	targets := []target{
		{title: "all activity", sources: []string{p.StewardEvents, p.ReviewerEvents, p.AuthorEvents}, level: "agent", meta: "merged"},
		{title: "steward", sources: []string{p.StewardEvents}, level: "agent", meta: serviceMeta(m.services, "steward")},
		{title: "reviewer", sources: []string{p.ReviewerEvents}, level: "agent", meta: serviceMeta(m.services, "reviewer")},
	}
	for _, r := range m.runs {
		lvl := "idle"
		meta := "idle"
		if r.Active {
			lvl = "running"
			meta = "running " + shortDur(r.Age())
		}
		targets = append(targets, target{
			title:     r.ID,
			meta:      meta,
			sources:   []string{r.EventsPath, p.StewardEvents, p.ReviewerEvents, p.AuthorEvents},
			runFilter: r.ID,
			active:    r.Active,
			level:     lvl,
		})
	}
	m.targets = targets
	if m.selected >= len(m.targets) {
		m.selected = len(m.targets) - 1
	}
	if m.selected < 0 {
		m.selected = 0
	}
}

func serviceMeta(services []state.Service, name string) string {
	for _, s := range services {
		if s.Name == name {
			if s.Up {
				return "up"
			}
			return "down"
		}
	}
	return ""
}

func (m *model) currentEvents() []state.Event {
	if len(m.targets) == 0 {
		return nil
	}
	t := m.targets[m.selected]
	evs := state.MergeEvents(t.sources, 0)
	out := evs[:0]
	for _, e := range evs {
		if t.runFilter != "" && e.RunID != t.runFilter {
			continue
		}
		if levelRank(e.Level) < m.minLevel {
			continue
		}
		out = append(out, e)
	}
	return out
}

func (m *model) refreshStream() {
	if !m.ready {
		return
	}
	evs := m.currentEvents()
	var b strings.Builder
	for i, e := range evs {
		if i > 0 {
			b.WriteByte('\n')
		}
		b.WriteString(formatEvent(e, m.vp.Width))
	}
	atBottom := m.vp.AtBottom()
	m.vp.SetContent(b.String())
	if m.follow || atBottom {
		m.vp.GotoBottom()
	}
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.layout()
		m.ready = true
		m.buildTargets()
		m.refreshStream()
		return m, nil

	case refreshMsg:
		m.services = msg.services
		m.runs = msg.runs
		m.prs = msg.prs
		m.prErr = msg.prErr
		m.queue = msg.queue
		m.updated = time.Now()
		m.buildTargets()
		m.refreshStream()
		return m, nil

	case tickMsg:
		return m, tea.Batch(m.refreshCmd(), tickCmd())

	case tea.KeyMsg:
		return m.handleKey(msg)
	}

	var cmd tea.Cmd
	m.vp, cmd = m.vp.Update(msg)
	return m, cmd
}

func (m model) handleKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "q", "ctrl+c":
		return m, tea.Quit
	case "?":
		m.showHelp = !m.showHelp
		return m, nil
	case "r":
		return m, m.refreshCmd()
	case "f":
		m.follow = !m.follow
		if m.follow {
			m.vp.GotoBottom()
		}
		return m, nil
	case "l":
		m.minLevel = (m.minLevel + 1) % 4
		m.refreshStream()
		return m, nil
	case "j", "down":
		if m.selected < len(m.targets)-1 {
			m.selected++
			m.refreshStream()
			m.vp.GotoBottom()
		}
		return m, nil
	case "k", "up":
		if m.selected > 0 {
			m.selected--
			m.refreshStream()
			m.vp.GotoBottom()
		}
		return m, nil
	case "g", "home":
		m.vp.GotoTop()
		return m, nil
	case "G", "end":
		m.vp.GotoBottom()
		return m, nil
	}
	// Forward scroll keys (pgup/pgdn, ctrl+u/d) to the stream pane.
	var cmd tea.Cmd
	m.vp, cmd = m.vp.Update(msg)
	return m, cmd
}

func (m *model) layout() {
	bodyH := m.height - 2 // header + footer
	if bodyH < 3 {
		bodyH = 3
	}
	rightW := m.width - railWidth(m.width) - 3
	if rightW < 10 {
		rightW = 10
	}
	vpH := bodyH - 1 // stream title line
	if vpH < 1 {
		vpH = 1
	}
	if m.vp.Width == 0 {
		m.vp = viewport.New(rightW, vpH)
	} else {
		m.vp.Width = rightW
		m.vp.Height = vpH
	}
}

func (m model) View() string {
	if !m.ready {
		return "loading fatop…"
	}
	if m.showHelp {
		return m.helpView()
	}
	header := m.headerView()
	body := lipgloss.JoinHorizontal(lipgloss.Top, m.railView(), m.streamView())
	footer := m.footerView()
	return lipgloss.JoinVertical(lipgloss.Left, header, body, footer)
}

func (m model) headerView() string {
	parts := []string{ui.Accent.Render("fatop")}
	for _, s := range m.services {
		if s.Name == "author" && !s.Up {
			continue // author is one-shot; only show when running
		}
		parts = append(parts, fmt.Sprintf("%s %s", ui.Dot(s.Up), s.Name))
	}
	active := 0
	for _, r := range m.runs {
		if r.Active {
			active++
		}
	}
	parts = append(parts, ui.Run.Render(fmt.Sprintf("authors %d", active)))
	if m.prErr == nil {
		parts = append(parts, ui.Muted.Render(fmt.Sprintf("%d PRs", len(m.prs))))
	} else {
		parts = append(parts, ui.Warn.Render("gh?"))
	}
	parts = append(parts, ui.Muted.Render(m.updated.Format("15:04:05")))
	line := strings.Join(parts, ui.Muted.Render("  ·  "))
	return lipgloss.NewStyle().Width(m.width).Padding(0, 1).Render(line)
}

func (m model) railView() string {
	w := railWidth(m.width)
	var b strings.Builder
	b.WriteString(ui.Muted.Render("AGENTS") + "\n")
	for i, t := range m.targets {
		if i == 3 && len(m.targets) > 3 {
			b.WriteString(ui.Muted.Render("RUNS") + "\n")
		}
		b.WriteString(m.railRow(t, i == m.selected, w) + "\n")
	}
	if len(m.queue) > 0 {
		b.WriteString("\n" + ui.Muted.Render("QUEUE — assignment order") + "\n")
		for _, q := range m.queue {
			b.WriteString(queueRow(q, w) + "\n")
		}
	}
	if m.prErr == nil && len(m.prs) > 0 {
		b.WriteString("\n" + ui.Muted.Render("OPEN PRS") + "\n")
		for _, pr := range m.prs {
			b.WriteString(prRow(pr, w) + "\n")
		}
	}
	box := lipgloss.NewStyle().
		Width(w).
		Height(m.height - 2).
		MaxHeight(m.height - 1).
		Border(lipgloss.RoundedBorder(), false, true, false, false).
		BorderForeground(ui.ColorMuted).
		Padding(0, 1)
	return box.Render(b.String())
}

func (m model) railRow(t target, selected bool, w int) string {
	icon := "·"
	style := lipgloss.NewStyle()
	switch t.level {
	case "running":
		icon, style = "●", ui.Run
	case "blocked":
		icon, style = "○", ui.Err
	case "agent":
		icon, style = "▸", ui.Accent
	default:
		icon, style = "○", ui.Muted
	}
	title := t.title
	label := fmt.Sprintf("%s %s", style.Render(icon), title)
	meta := ui.Muted.Render(t.meta)
	row := fitRow(label, meta, w-3)
	if selected {
		return lipgloss.NewStyle().Background(ui.ColorAccent).Foreground(lipgloss.Color("#FFFFFF")).Render(row)
	}
	return row
}

func queueRow(q state.QueueStory, w int) string {
	icon, style := "○", ui.Muted
	meta := ui.Muted.Render(q.Lane)
	switch {
	case q.Active:
		icon, style = "●", ui.Run
		meta = ui.Run.Render("running")
	case q.Tripped():
		icon, style = "⚠", ui.Err
		meta = ui.Err.Render("attention")
	case q.Blocked():
		icon, style = "○", ui.Warn
		meta = ui.Warn.Render("⟂ " + strings.Join(q.UnmetDeps, ","))
	default:
		icon, style = "○", ui.OK
	}
	label := fmt.Sprintf("%s %s", style.Render(icon), q.ID)
	return fitRow(label, meta, w-3)
}

func prRow(pr state.PR, w int) string {
	badge := reviewWord(pr)
	label := fmt.Sprintf("#%d %s", pr.Number, truncate(pr.Title, w-14))
	return fitRow(ui.Muted.Render(label), badge, w-3)
}

func (m model) streamView() string {
	t := target{title: "—"}
	if len(m.targets) > 0 {
		t = m.targets[m.selected]
	}
	flag := ""
	if m.follow {
		flag = ui.OK.Render(" following")
	} else {
		flag = ui.Muted.Render(" paused")
	}
	title := ui.Bold.Render("stream — "+t.title) + ui.Muted.Render(levelLabel(m.minLevel)) + flag
	return lipgloss.JoinVertical(lipgloss.Left, title, m.vp.View())
}

func (m model) footerView() string {
	keys := []string{"↑/↓ select", "f follow", "l level", "g/G top/bottom", "r reload", "? help", "q quit"}
	return lipgloss.NewStyle().Width(m.width).Padding(0, 1).Foreground(ui.ColorMuted).Render(strings.Join(keys, "  ·  "))
}

func (m model) helpView() string {
	body := strings.Join([]string{
		ui.Accent.Render("fatop — keys"),
		"",
		"  ↑/k, ↓/j     move selection in the left rail",
		"  enter        (rail) follow that run's stream",
		"  f            toggle follow (auto-scroll to newest)",
		"  l            cycle minimum level (debug→info→warn→error)",
		"  g / G        jump to top / bottom of the stream",
		"  pgup/pgdn    scroll the stream",
		"  r            force a refresh now",
		"  ?            toggle this help",
		"  q            quit",
		"",
		ui.Muted.Render("Reads structured events from the command-centre agents."),
		ui.Muted.Render("See docs/agent-event-log.md."),
	}, "\n")
	return lipgloss.NewStyle().Padding(1, 2).Render(body)
}

func railWidth(total int) int {
	w := total / 3
	if w < 26 {
		w = 26
	}
	if w > 40 {
		w = 40
	}
	return w
}
