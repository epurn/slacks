// Package tui implements the live fatop dashboard with Bubble Tea. It is a
// multi-view, k9s-style monitor: an overview, the story queue, token/cost usage,
// and a story-inspect view, all over the read-only command-centre state.
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
	p := tea.NewProgram(newModel(paths), tea.WithAltScreen())
	_, err := p.Run()
	return err
}

const refreshEvery = 2 * time.Second

type viewMode int

const (
	viewOverview viewMode = iota
	viewQueue
	viewUsage
	viewStory
)

var tabs = []struct {
	mode  viewMode
	key   string
	label string
}{
	{viewOverview, "1", "Overview"},
	{viewQueue, "2", "Queue"},
	{viewUsage, "3", "Usage"},
}

// target is one selectable event source in the overview rail.
type target struct {
	title     string
	meta      string
	sources   []string
	runFilter string
	level     string // running | agent | idle
}

type refreshMsg struct {
	services []state.Service
	runs     []state.Run
	prs      []state.PR
	prErr    error
	queue    []state.QueueStory
	usage    state.UsageSummary
	reviews  []int
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
	usage    state.UsageSummary
	reviews  []int

	view       viewMode
	returnView viewMode // where esc goes back to from the story view

	targets  []target // overview rail
	selected int      // overview rail selection
	queueSel int      // queue table selection
	storyID  string   // currently inspected story

	vp       viewport.Model // scrollable pane: stream / usage / story
	follow   bool
	minLevel int
	showHelp bool

	updated time.Time
}

func newModel(paths config.Paths) model {
	return model{paths: paths, follow: true, minLevel: 1, view: viewOverview}
}

func (m model) Init() tea.Cmd { return tea.Batch(m.refreshCmd(), tickCmd()) }

func (m model) refreshCmd() tea.Cmd {
	p := m.paths
	return func() tea.Msg {
		services := state.LoadServices()
		runs, _ := state.LoadRuns(p.RunDir)
		prs, prErr := state.LoadPRs(p.Repo)
		queue, _ := state.LoadQueue(p.Roadmap, p.StoriesDir, p.RunDir)
		events := state.MergeEvents([]string{p.AuthorEvents, p.ReviewerEvents}, 0)
		usage := state.SummarizeUsage(state.CollectUsage(events), startOfDay())
		reviews := state.ReviewsInFlight(p.RunDir)
		return refreshMsg{services: services, runs: runs, prs: prs, prErr: prErr, queue: queue, usage: usage, reviews: reviews}
	}
}

func tickCmd() tea.Cmd {
	return tea.Tick(refreshEvery, func(t time.Time) tea.Msg { return tickMsg(t) })
}

func startOfDay() time.Time {
	n := time.Now()
	return time.Date(n.Year(), n.Month(), n.Day(), 0, 0, 0, 0, n.Location())
}

func (m *model) buildTargets() {
	p := m.paths
	targets := []target{
		{title: "all activity", sources: []string{p.StewardEvents, p.ReviewerEvents, p.AuthorEvents}, level: "agent", meta: "merged"},
		{title: "steward", sources: []string{p.StewardEvents}, level: "agent", meta: serviceMeta(m.services, "steward")},
		{title: "reviewer", sources: []string{p.ReviewerEvents}, level: "agent", meta: serviceMeta(m.services, "reviewer")},
	}
	for _, r := range m.runs {
		meta, lvl := "idle", "idle"
		if r.Active {
			meta, lvl = "running "+shortDur(r.Age()), "running"
		}
		targets = append(targets, target{
			title:     r.ID,
			meta:      meta,
			sources:   []string{r.EventsPath, p.StewardEvents, p.ReviewerEvents, p.AuthorEvents},
			runFilter: r.ID,
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

// --- refresh content for the scrollable pane, per view ---

func (m *model) refreshView() {
	if !m.ready {
		return
	}
	switch m.view {
	case viewOverview:
		m.setStreamContent()
	case viewUsage:
		m.vp.SetContent(m.usageContent(m.vp.Width))
		if m.follow {
			m.vp.GotoTop()
		}
	case viewStory:
		m.vp.SetContent(m.storyContent(m.vp.Width))
	}
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

func (m *model) setStreamContent() {
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
		m.refreshView()
		return m, nil

	case refreshMsg:
		m.services, m.runs, m.prs, m.prErr = msg.services, msg.runs, msg.prs, msg.prErr
		m.queue, m.usage, m.reviews = msg.queue, msg.usage, msg.reviews
		m.updated = time.Now()
		m.buildTargets()
		m.clampQueue()
		m.refreshView()
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

func (m *model) clampQueue() {
	if m.queueSel >= len(m.queue) {
		m.queueSel = len(m.queue) - 1
	}
	if m.queueSel < 0 {
		m.queueSel = 0
	}
}

func (m model) switchView(v viewMode) (tea.Model, tea.Cmd) {
	m.view = v
	m.layout()
	m.refreshView()
	return m, nil
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
	case "1":
		return m.switchView(viewOverview)
	case "2":
		return m.switchView(viewQueue)
	case "3":
		return m.switchView(viewUsage)
	case "tab":
		return m.switchView((m.view + 1) % 3) // cycle the three primary tabs
	case "esc":
		if m.view == viewStory {
			return m.switchView(m.returnView)
		}
		return m, nil
	}
	if m.showHelp {
		return m, nil
	}

	switch m.view {
	case viewOverview:
		return m.handleOverviewKey(msg)
	case viewQueue:
		return m.handleQueueKey(msg)
	case viewUsage, viewStory:
		var cmd tea.Cmd
		m.vp, cmd = m.vp.Update(msg)
		return m, cmd
	}
	return m, nil
}

func (m model) handleOverviewKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "f":
		m.follow = !m.follow
		if m.follow {
			m.vp.GotoBottom()
		}
		return m, nil
	case "l":
		m.minLevel = (m.minLevel + 1) % 4
		m.setStreamContent()
		return m, nil
	case "j", "down":
		if m.selected < len(m.targets)-1 {
			m.selected++
			m.setStreamContent()
			m.vp.GotoBottom()
		}
		return m, nil
	case "k", "up":
		if m.selected > 0 {
			m.selected--
			m.setStreamContent()
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
	var cmd tea.Cmd
	m.vp, cmd = m.vp.Update(msg)
	return m, cmd
}

func (m model) handleQueueKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "j", "down":
		if m.queueSel < len(m.queue)-1 {
			m.queueSel++
		}
		return m, nil
	case "k", "up":
		if m.queueSel > 0 {
			m.queueSel--
		}
		return m, nil
	case "g", "home":
		m.queueSel = 0
		return m, nil
	case "G", "end":
		m.queueSel = len(m.queue) - 1
		return m, nil
	case "enter":
		if m.queueSel >= 0 && m.queueSel < len(m.queue) {
			m.storyID = m.queue[m.queueSel].ID
			m.returnView = viewQueue
			return m.switchView(viewStory)
		}
	}
	return m, nil
}

func (m *model) layout() {
	bodyH := m.height - 3 // header + tab bar + footer
	if bodyH < 3 {
		bodyH = 3
	}
	var vpW, vpH int
	switch m.view {
	case viewOverview:
		vpW = m.width - railWidth(m.width) - 3
		vpH = bodyH - 1 // pane title line
	default:
		vpW = m.width - 2
		vpH = bodyH - 1
	}
	if vpW < 10 {
		vpW = 10
	}
	if vpH < 1 {
		vpH = 1
	}
	if m.vp.Width == 0 {
		m.vp = viewport.New(vpW, vpH)
	} else {
		m.vp.Width, m.vp.Height = vpW, vpH
	}
}

// --- top-level view ---

func (m model) View() string {
	if !m.ready {
		return "loading fatop…"
	}
	if m.showHelp {
		return m.helpView()
	}
	var body string
	switch m.view {
	case viewOverview:
		body = lipgloss.JoinHorizontal(lipgloss.Top, m.railView(), m.streamPane())
	case viewQueue:
		body = m.queueView()
	case viewUsage:
		body = m.paneTitled("usage — today + recent runs")
	case viewStory:
		body = m.paneTitled("story — " + m.storyID + "   " + ui.Muted.Render("esc back"))
	}
	return lipgloss.JoinVertical(lipgloss.Left, m.headerView(), m.tabBar(), body, m.footerView())
}

func (m model) headerView() string {
	parts := []string{ui.Accent.Render("fatop")}
	for _, s := range m.services {
		if s.OnDemand {
			continue // one-shot workers show as activity counts below, not health dots
		}
		parts = append(parts, fmt.Sprintf("%s %s", ui.Dot(s.Up), s.Name))
	}
	active := 0
	for _, r := range m.runs {
		if r.Active {
			active++
		}
	}
	work := ui.Run.Render(fmt.Sprintf("⚙ %d authors", active))
	if len(m.reviews) > 0 {
		work += ui.Muted.Render(" · ") + ui.Run.Render(fmt.Sprintf("%d reviews", len(m.reviews)))
	}
	parts = append(parts, work)

	// Cost stat — always visible.
	cost := "today " + ui.Cost.Render(fmtUSD(m.usage.CostUSD))
	if br := m.usage.BurnRateUSDPerHour(); br > 0 {
		cost += ui.Muted.Render(" · "+fmtUSD(br)+"/h")
	}
	parts = append(parts, cost)

	if m.prErr == nil {
		parts = append(parts, ui.Muted.Render(fmt.Sprintf("%d PRs", len(m.prs))))
	} else {
		parts = append(parts, ui.Warn.Render("gh?"))
	}
	parts = append(parts, ui.Muted.Render(m.updated.Format("15:04:05")))
	line := strings.Join(parts, ui.Muted.Render("  ·  "))
	return lipgloss.NewStyle().Width(m.width).Padding(0, 1).Render(line)
}

func (m model) tabBar() string {
	var cells []string
	for _, t := range tabs {
		label := t.key + " " + t.label
		if m.view == t.mode || (m.view == viewStory && t.mode == viewQueue) {
			cells = append(cells, ui.TabActive.Render(label))
		} else {
			cells = append(cells, ui.TabInactive.Render(label))
		}
	}
	bar := strings.Join(cells, " ")
	return lipgloss.NewStyle().Width(m.width).Padding(0, 1).Render(bar)
}

func (m model) footerView() string {
	var keys []string
	switch m.view {
	case viewOverview:
		keys = []string{"1/2/3 view", "↑/↓ select", "f follow", "l level", "g/G top/bot", "r reload", "? help", "q quit"}
	case viewQueue:
		keys = []string{"1/2/3 view", "↑/↓ move", "↵ inspect story", "r reload", "? help", "q quit"}
	case viewUsage:
		keys = []string{"1/2/3 view", "pgup/pgdn scroll", "r reload", "? help", "q quit"}
	case viewStory:
		keys = []string{"esc back", "↑/↓ pgup/pgdn scroll", "g/G top/bot", "q quit"}
	}
	return lipgloss.NewStyle().Width(m.width).Padding(0, 1).Foreground(ui.ColorMuted).Render(strings.Join(keys, "  ·  "))
}

// paneTitled renders a single-pane view (usage/story): a title + the viewport.
func (m model) paneTitled(title string) string {
	return lipgloss.JoinVertical(lipgloss.Left, ui.PanelTitle.Render(title), m.vp.View())
}

// --- overview ---

func (m model) railView() string {
	w := railWidth(m.width)
	var b strings.Builder
	b.WriteString(ui.TableHead.Render("AGENTS") + "\n")
	for i, t := range m.targets {
		if i == 3 && len(m.targets) > 3 {
			b.WriteString("\n" + ui.TableHead.Render("RUNS") + "\n")
		}
		b.WriteString(m.railRow(t, i == m.selected, w) + "\n")
	}
	// Queue summary: next assignable + counts.
	if len(m.queue) > 0 {
		var ready, blocked, attn int
		for _, q := range m.queue {
			switch {
			case q.Tripped():
				attn++
			case q.Active:
			case q.Blocked():
				blocked++
			default:
				ready++
			}
		}
		b.WriteString("\n" + ui.TableHead.Render("QUEUE") + ui.Muted.Render(fmt.Sprintf("  %d ready · %d blocked", ready, blocked)))
		if attn > 0 {
			b.WriteString(ui.Err.Render(fmt.Sprintf(" · %d ⚠", attn)))
		}
		b.WriteByte('\n')
		shown := 0
		for _, q := range m.queue {
			if q.Tripped() || q.Blocked() {
				continue
			}
			b.WriteString(queueRailRow(q, w) + "\n")
			if shown++; shown >= 5 {
				break
			}
		}
	}
	if m.prErr == nil && len(m.prs) > 0 {
		b.WriteString("\n" + ui.TableHead.Render("OPEN PRS") + "\n")
		for _, pr := range m.prs {
			b.WriteString(prRow(pr, w) + "\n")
		}
	}
	box := lipgloss.NewStyle().
		Width(w).Height(m.height - 3).MaxHeight(m.height - 2).
		Border(lipgloss.RoundedBorder(), false, true, false, false).
		BorderForeground(ui.ColorMuted).Padding(0, 1)
	return box.Render(b.String())
}

func (m model) railRow(t target, selected bool, w int) string {
	icon, style := "○", ui.Muted
	switch t.level {
	case "running":
		icon, style = "●", ui.Run
	case "agent":
		icon, style = "▸", ui.Accent
	}
	row := fitRow(fmt.Sprintf("%s %s", style.Render(icon), t.title), ui.Muted.Render(t.meta), w-3)
	if selected {
		return ui.Selected.Render(row)
	}
	return row
}

func queueRailRow(q state.QueueStory, w int) string {
	icon, style := "○", ui.OK
	meta := ui.Muted.Render(q.Lane)
	if q.Active {
		icon, style, meta = "●", ui.Run, ui.Run.Render("running")
	}
	return fitRow(fmt.Sprintf("%s %s", style.Render(icon), q.ID), meta, w-3)
}

func prRow(pr state.PR, w int) string {
	return fitRow(ui.Muted.Render(fmt.Sprintf("#%d %s", pr.Number, truncate(pr.Title, w-14))), reviewWord(pr), w-3)
}

func (m model) streamPane() string {
	t := target{title: "—"}
	if len(m.targets) > 0 {
		t = m.targets[m.selected]
	}
	flag := ui.Muted.Render(" paused")
	if m.follow {
		flag = ui.OK.Render(" following")
	}
	title := ui.PanelTitle.Render("stream — "+t.title) + ui.Muted.Render(levelLabel(m.minLevel)) + flag
	return lipgloss.JoinVertical(lipgloss.Left, title, m.vp.View())
}

// --- queue view (full table, selectable) ---

func (m model) queueView() string {
	w := m.width - 2
	bodyH := m.height - 3
	idW, stW, laneW, statusW := 9, 16, 15, 22
	titleW := w - idW - stW - laneW - statusW - 6
	if titleW < 10 {
		titleW = 10
	}
	head := fmt.Sprintf("  %s %s %s %s %s",
		pad("ID", idW), pad("STATE", stW), pad("LANE", laneW), pad("STATUS", statusW), "TITLE")
	rows := []string{ui.TableHead.Render(head)}

	visible := bodyH - 1
	if visible < 1 {
		visible = 1
	}
	start := 0
	if m.queueSel >= visible {
		start = m.queueSel - visible + 1
	}
	for i := start; i < len(m.queue) && i < start+visible; i++ {
		q := m.queue[i]
		status := queueStatus(q)
		line := fmt.Sprintf("  %s %s %s %s %s",
			ui.Bold.Render(pad(q.ID, idW)), pad(q.State, stW), ui.Muted.Render(pad(q.Lane, laneW)),
			padStyled(status, statusW), truncate(q.Title, titleW))
		if i == m.queueSel {
			line = ui.Selected.Render("▶ " + stripLeading(line))
		}
		rows = append(rows, line)
	}
	if len(m.queue) == 0 {
		rows = append(rows, ui.Muted.Render("  (queue empty)"))
	}
	return lipgloss.JoinVertical(lipgloss.Left, ui.PanelTitle.Render("queue — assignment order"), strings.Join(rows, "\n"))
}

func queueStatus(q state.QueueStory) string {
	switch {
	case q.Active:
		return ui.Run.Render("running")
	case q.Tripped():
		s := ui.Err.Render("⚠ attention")
		if q.Attempts > 0 {
			s += ui.Muted.Render(fmt.Sprintf(" %dx", q.Attempts))
		}
		return s
	case q.Blocked():
		return ui.Warn.Render("⟂ " + strings.Join(q.UnmetDeps, ","))
	default:
		return ui.OK.Render("ready")
	}
}

// --- usage view ---

func (m model) usageContent(w int) string {
	s := m.usage
	var b strings.Builder
	if s.Runs == 0 {
		return ui.Muted.Render("no completed runs today — try a wider window with `fatop usage --since all`")
	}
	b.WriteString(ui.Bold.Render("today") + "  ")
	b.WriteString(fmt.Sprintf("%d runs · %s · ", s.Runs, ui.Cost.Render(fmtUSD(s.CostUSD))))
	if br := s.BurnRateUSDPerHour(); br > 0 {
		b.WriteString(fmtUSD(br) + "/h · ")
	}
	b.WriteString(fmt.Sprintf("%s cache hit · %d turns\n", pct(s.CacheHitRatio()), s.Turns))
	b.WriteString(ui.Muted.Render(fmt.Sprintf("tokens: %s in · %s out · %s cache-read\n\n",
		fmtTokens(s.InputTokens+s.CacheCreateTokens), fmtTokens(s.OutputTokens), fmtTokens(s.CacheReadTokens))))

	b.WriteString(ui.TableHead.Render("by model") + "\n")
	for _, mu := range s.ModelsByCost() {
		b.WriteString(fmt.Sprintf("  %s %s  %s  %s out · %d turns\n",
			pad(mu.Model, 10), pad(fmt.Sprintf("%d runs", mu.Runs), 8),
			ui.Cost.Render(fmtUSD(mu.CostUSD)), fmtTokens(mu.OutputTokens), mu.Turns))
	}
	b.WriteString("\n" + ui.TableHead.Render("recent runs") + "\n")
	recs := s.Records
	for i := len(recs) - 1; i >= 0 && i >= len(recs)-30; i-- {
		r := recs[i]
		ts := "--:--"
		if !r.Ts.IsZero() {
			ts = r.Ts.Local().Format("15:04")
		}
		mode := r.Mode
		if mode == "" {
			mode = "review"
		}
		b.WriteString(fmt.Sprintf("  %s %s %s %s %dt  %s  %s\n",
			ui.Muted.Render(ts), ui.Run.Render(pad(r.RunID, 9)), pad(r.Model, 7),
			ui.Muted.Render(pad(mode, 9)), r.Turns, ui.Cost.Render(fmtUSD(r.CostUSD)),
			ui.Muted.Render(fmt.Sprintf("%s out · %s cache", fmtTokens(r.OutputTokens), pct(r.CacheHitRatio())))))
	}
	return b.String()
}

// --- story inspect view ---

func (m model) storyContent(w int) string {
	var q *state.QueueStory
	for i := range m.queue {
		if m.queue[i].ID == m.storyID {
			q = &m.queue[i]
			break
		}
	}
	if q == nil {
		return ui.Muted.Render("story not in the current queue (it may have merged)")
	}
	var b strings.Builder
	b.WriteString(queueStatus(*q) + "  " + ui.Muted.Render(q.Lane))
	if len(q.Deps) > 0 {
		b.WriteString(ui.Muted.Render("  deps: " + strings.Join(q.Deps, ", ")))
	}
	b.WriteString("\n\n")
	b.WriteString(renderMarkdown(state.StoryContent(q.Path), w))
	return b.String()
}

// renderMarkdown lightly styles a story file for the inspect pane.
func renderMarkdown(content string, w int) string {
	var b strings.Builder
	inFront := false
	for i, line := range strings.Split(content, "\n") {
		switch {
		case line == "---" && i == 0:
			inFront = true
			b.WriteString(ui.Muted.Render("─── front matter ───"))
		case line == "---" && inFront:
			inFront = false
			b.WriteString(ui.Muted.Render("────────────────────"))
		case inFront:
			b.WriteString(ui.Muted.Render(line))
		case strings.HasPrefix(line, "# "):
			b.WriteString(ui.Accent.Render(line))
		case strings.HasPrefix(line, "## "):
			b.WriteString(ui.PanelTitle.Render(line))
		case strings.HasPrefix(line, "> "):
			for _, wl := range wordWrap(line, w) {
				b.WriteString(ui.Warn.Render(wl) + "\n")
			}
			continue
		default:
			for _, wl := range wordWrap(line, w) {
				b.WriteString(wl + "\n")
			}
			continue
		}
		b.WriteByte('\n')
	}
	return b.String()
}

func (m model) helpView() string {
	body := strings.Join([]string{
		ui.Accent.Render("fatop — keys"),
		"",
		"  1 / 2 / 3     switch view: Overview · Queue · Usage",
		"  tab           cycle views",
		"  ↑/k ↓/j       move selection (overview rail / queue rows)",
		"  enter         (queue) inspect the selected story's spec",
		"  esc           (story) back to the queue",
		"  f             (overview) toggle follow on the stream",
		"  l             (overview) cycle minimum level",
		"  g / G         jump to top / bottom",
		"  pgup/pgdn     scroll",
		"  r             force a refresh now",
		"  ? · q         toggle help · quit",
		"",
		ui.Muted.Render("Read-only over the command-centre state. See docs/agent-event-log.md."),
	}, "\n")
	return lipgloss.NewStyle().Padding(1, 2).Render(body)
}

func railWidth(total int) int {
	w := total / 3
	if w < 28 {
		w = 28
	}
	if w > 42 {
		w = 42
	}
	return w
}

// padStyled right-pads a possibly-styled cell to n visible columns.
func padStyled(s string, n int) string {
	gap := n - lipgloss.Width(s)
	if gap > 0 {
		return s + strings.Repeat(" ", gap)
	}
	return s
}

// stripLeading trims the two leading spaces used for unselected rows so the
// selection caret lines up.
func stripLeading(s string) string { return strings.TrimPrefix(s, "  ") }
