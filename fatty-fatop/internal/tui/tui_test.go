package tui

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/epurn/fatty-fatop/internal/config"
	"github.com/epurn/fatty-fatop/internal/state"
)

// drive feeds a message and returns the updated model, failing on a non-model.
func drive(t *testing.T, m model, msg tea.Msg) model {
	t.Helper()
	next, _ := m.Update(msg)
	nm, ok := next.(model)
	if !ok {
		t.Fatalf("Update returned %T, want model", next)
	}
	return nm
}

// TestViewsRenderWithoutPanic exercises every view's render path with realistic
// data. The TUI can't be driven in a TTY here, so this is the guard that a view
// redesign doesn't panic on indexing, an empty queue, or a missing story.
func TestViewsRenderWithoutPanic(t *testing.T) {
	m := newModel(config.Paths{})
	m = drive(t, m, tea.WindowSizeMsg{Width: 100, Height: 30})

	usage := state.SummarizeUsage([]state.UsageRecord{
		{Agent: "author", RunID: "FTY-053", Model: "opus", Mode: "implement", OutputTokens: 5000, CacheReadTokens: 90000, InputTokens: 1000, CostUSD: 6.5, Turns: 80},
	}, state.UsageRecord{}.Ts) // zero time → include all

	m = drive(t, m, refreshMsg{
		services: []state.Service{{Name: "steward", Up: true}, {Name: "reviewer", Up: true}},
		runs:     []state.Run{{ID: "FTY-053", Mode: "implement", Active: true}},
		prs:      []state.PR{{Number: 9, Title: "x", Review: "APPROVED"}},
		queue: []state.QueueStory{
			{ID: "FTY-053", State: "ready", Lane: "mobile-core", Active: true, Path: "/nonexistent.md"},
			{ID: "FTY-061", State: "ready", Lane: "estimator", Deps: []string{"FTY-077"}, UnmetDeps: []string{"FTY-077"}},
			{ID: "FTY-099", State: "needs_attention", Lane: "infra", Attempts: 3},
		},
		usage: usage,
	})

	for _, v := range []viewMode{viewOverview, viewQueue, viewUsage} {
		mv, _ := m.switchView(v)
		out := mv.(model).View()
		if strings.TrimSpace(out) == "" {
			t.Errorf("view %d rendered empty", v)
		}
	}

	// Inspect a story (enter on the queue), then render the story view.
	mq, _ := m.switchView(viewQueue)
	m = mq.(model)
	m.queueSel = 1 // FTY-061
	ms, _ := m.handleQueueKey(tea.KeyMsg{Type: tea.KeyEnter})
	m = ms.(model)
	if m.view != viewStory || m.storyID != "FTY-061" {
		t.Fatalf("enter should open story view for FTY-061, got view=%d id=%q", m.view, m.storyID)
	}
	if strings.TrimSpace(m.View()) == "" {
		t.Error("story view rendered empty")
	}

	// esc returns to the queue.
	me, _ := m.handleKey(tea.KeyMsg{Type: tea.KeyEsc})
	if me.(model).view != viewQueue {
		t.Error("esc from story should return to queue")
	}

	// Empty queue must not panic.
	m.queue = nil
	mq2, _ := m.switchView(viewQueue)
	if strings.TrimSpace(mq2.(model).View()) == "" {
		t.Error("empty queue view rendered empty")
	}
}
