// Package ui holds the lipgloss palette shared by the CLI and the TUI so fatop
// looks consistent everywhere.
package ui

import "github.com/charmbracelet/lipgloss"

var (
	// Adaptive colors so fatop reads well on light and dark terminals.
	ColorAccent  = lipgloss.AdaptiveColor{Light: "#6C3FC5", Dark: "#B794F6"}
	ColorOK      = lipgloss.AdaptiveColor{Light: "#1E7F4F", Dark: "#4ADE80"}
	ColorWarn    = lipgloss.AdaptiveColor{Light: "#B45309", Dark: "#FBBF24"}
	ColorErr     = lipgloss.AdaptiveColor{Light: "#B91C1C", Dark: "#F87171"}
	ColorMuted   = lipgloss.AdaptiveColor{Light: "#6B7280", Dark: "#9CA3AF"}
	ColorRunning = lipgloss.AdaptiveColor{Light: "#0E7490", Dark: "#22D3EE"}

	Bold   = lipgloss.NewStyle().Bold(true)
	Accent = lipgloss.NewStyle().Foreground(ColorAccent).Bold(true)
	OK     = lipgloss.NewStyle().Foreground(ColorOK)
	Warn   = lipgloss.NewStyle().Foreground(ColorWarn)
	Err    = lipgloss.NewStyle().Foreground(ColorErr)
	Muted  = lipgloss.NewStyle().Foreground(ColorMuted)
	Run    = lipgloss.NewStyle().Foreground(ColorRunning)

	// Chrome for the redesigned multi-view dashboard.
	PanelTitle  = lipgloss.NewStyle().Foreground(ColorAccent).Bold(true)
	TabActive   = lipgloss.NewStyle().Foreground(lipgloss.Color("#FFFFFF")).Background(ColorAccent).Bold(true).Padding(0, 1)
	TabInactive = lipgloss.NewStyle().Foreground(ColorMuted).Padding(0, 1)
	Selected    = lipgloss.NewStyle().Background(ColorAccent).Foreground(lipgloss.Color("#FFFFFF"))
	Cost        = lipgloss.NewStyle().Foreground(ColorWarn).Bold(true)
	TableHead   = lipgloss.NewStyle().Foreground(ColorMuted).Bold(true)
)

// Border returns a rounded border style for a panel of the given inner width.
func Border() lipgloss.Style {
	return lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(ColorMuted)
}

// Dot returns a colored status dot for an up/down state.
func Dot(up bool) string {
	if up {
		return OK.Render("●")
	}
	return Err.Render("○")
}

// LevelStyle maps an event level to a style.
func LevelStyle(level string) lipgloss.Style {
	switch level {
	case "error":
		return Err
	case "warn":
		return Warn
	case "debug":
		return Muted
	default:
		return lipgloss.NewStyle()
	}
}

// EventIcon returns an icon for an event kind/level for the stream view.
func EventIcon(eventT, kind string) string {
	switch {
	case kind == "tool_use" || eventT == "verify":
		return "⚙"
	case kind == "result" || eventT == "run_result":
		return "✓"
	case eventT == "review_posted" || eventT == "auto_merge_enabled":
		return "✓"
	case eventT == "pr_blocked" || eventT == "steward_judgment":
		return "⚠"
	case eventT == "author_launch" || eventT == "run_start" || eventT == "review_start":
		return "▸"
	case eventT == "decision":
		return "•"
	default:
		return "·"
	}
}
