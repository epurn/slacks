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

func TestLoadRunsClearsMergedIdleRuns(t *testing.T) {
	dir := t.TempDir()
	// Idle author whose story has merged → should be cleared from in-flight runs.
	os.WriteFile(filepath.Join(dir, "FTY-061.json"), []byte(
		`{"story_id":"FTY-061","repo":"epurn/fatty","worktree":"/wt/fty-061"}`), 0o644)
	// Idle author still open (not merged) → must remain visible.
	os.WriteFile(filepath.Join(dir, "FTY-062.json"), []byte(
		`{"story_id":"FTY-062","repo":"epurn/fatty","worktree":"/wt/fty-062"}`), 0o644)
	// A merged story that is STILL active (live process) → must stay visible.
	os.WriteFile(filepath.Join(dir, "FTY-063.json"), []byte(
		`{"story_id":"FTY-063","repo":"epurn/fatty","worktree":"/wt/fty-063"}`), 0o644)
	os.WriteFile(filepath.Join(dir, "FTY-063.active"), []byte("1"), 0o644)
	os.WriteFile(filepath.Join(dir, "merged-stories.json"), []byte(
		`["FTY-061","FTY-063"]`), 0o644)

	runs, err := LoadRuns(dir)
	if err != nil {
		t.Fatal(err)
	}
	ids := map[string]bool{}
	for _, r := range runs {
		ids[r.ID] = true
	}
	if ids["FTY-061"] {
		t.Error("merged idle run FTY-061 should be cleared")
	}
	if !ids["FTY-062"] {
		t.Error("unmerged idle run FTY-062 should remain")
	}
	if !ids["FTY-063"] {
		t.Error("merged but still-active run FTY-063 must stay visible")
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
