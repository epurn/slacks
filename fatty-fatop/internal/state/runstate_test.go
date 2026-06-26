package state

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadRuns(t *testing.T) {
	dir := t.TempDir()
	// An active implement run.
	os.WriteFile(filepath.Join(dir, "FTY-010.json"), []byte(
		`{"story_id":"FTY-010","lanes":["contracts","backend-core"],"repo":"epurn/fatty","worktree":"/wt/fty-010"}`), 0o644)
	os.WriteFile(filepath.Join(dir, "FTY-010.active"), []byte("123"), 0o644)
	// An idle fix-pr run inferred from the id prefix.
	os.WriteFile(filepath.Join(dir, "PR-6.json"), []byte(
		`{"story_id":"PR-6","lanes":["governance"],"mode":"fix-pr","repo":"epurn/fatty"}`), 0o644)
	// Steward bookkeeping (a JSON array of merged ids) must NOT show as a run.
	os.WriteFile(filepath.Join(dir, "merged-stories.json"), []byte(
		`["FTY-040","FTY-041"]`), 0o644)

	runs, err := LoadRuns(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(runs) != 2 {
		t.Fatalf("got %d runs, want 2 (merged-stories must be excluded)", len(runs))
	}
	for _, r := range runs {
		if r.ID == "merged-stories" {
			t.Fatal("merged-stories.json must not be rendered as a run")
		}
	}
	// Active run sorts first.
	if runs[0].ID != "FTY-010" || !runs[0].Active {
		t.Fatalf("expected active FTY-010 first, got %+v", runs[0])
	}
	if runs[0].Mode != "implement" {
		t.Fatalf("default mode = %q want implement", runs[0].Mode)
	}
	if runs[1].ID != "PR-6" || runs[1].Active {
		t.Fatalf("expected idle PR-6 second, got %+v", runs[1])
	}
	if runs[1].Mode != "fix-pr" {
		t.Fatalf("PR mode = %q want fix-pr", runs[1].Mode)
	}
	if runs[0].EventsPath != filepath.Join(dir, "FTY-010.events.jsonl") {
		t.Fatalf("events path = %q", runs[0].EventsPath)
	}
}

func TestLoadRunsMissingDir(t *testing.T) {
	runs, err := LoadRuns(filepath.Join(t.TempDir(), "nope"))
	if err != nil {
		t.Fatalf("missing dir should not error: %v", err)
	}
	if len(runs) != 0 {
		t.Fatal("expected no runs")
	}
}
