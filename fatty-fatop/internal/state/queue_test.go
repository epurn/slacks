package state

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadQueue(t *testing.T) {
	dir := t.TempDir()
	stories := filepath.Join(dir, "stories")
	runDir := filepath.Join(dir, "run")
	if err := os.MkdirAll(stories, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatal(err)
	}

	write := func(name, body string) {
		if err := os.WriteFile(filepath.Join(stories, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	// FTY-001 merged; FTY-002 ready (dep on merged 001 → assignable);
	// FTY-003 ready but dep on unmerged 002 → blocked; FTY-004 needs_attention.
	write("a.md", "---\nid: FTY-002\n---\n## Dependencies\n- FTY-001\n")
	write("b.md", "---\nid: FTY-003\n---\n## Dependencies\n- FTY-002\n")
	write("c.md", "---\nid: FTY-004\n---\n")

	roadmap := filepath.Join(dir, "roadmap.md")
	if err := os.WriteFile(roadmap, []byte(
		"| ID | State | Lane | Story | Acceptance |\n"+
			"| --- | --- | --- | --- | --- |\n"+
			"| FTY-001 | merged | core | [a](a.md) | x |\n"+
			"| FTY-002 | ready | core | [b](a.md) | x |\n"+
			"| FTY-003 | ready | core | [c](b.md) | x |\n"+
			"| FTY-004 | needs_attention | core | [d](c.md) | x |\n",
	), 0o644); err != nil {
		t.Fatal(err)
	}

	// FTY-002 is running; FTY-004 has 3 attempts on the breaker.
	if err := os.WriteFile(filepath.Join(runDir, "FTY-002.active"), []byte("now"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "attempts.json"), []byte(`{"FTY-004": 3}`), 0o644); err != nil {
		t.Fatal(err)
	}

	q, err := LoadQueue(roadmap, stories, runDir)
	if err != nil {
		t.Fatal(err)
	}
	// Merged FTY-001 excluded; 002/003/004 present in roadmap order.
	if len(q) != 3 {
		t.Fatalf("expected 3 queue rows, got %d: %+v", len(q), q)
	}
	if q[0].ID != "FTY-002" || !q[0].Active {
		t.Errorf("FTY-002 should be first and active: %+v", q[0])
	}
	if q[0].Blocked() {
		t.Errorf("FTY-002 dep on merged FTY-001 should not be blocked")
	}
	if !q[1].Blocked() || len(q[1].UnmetDeps) != 1 || q[1].UnmetDeps[0] != "FTY-002" {
		t.Errorf("FTY-003 should be blocked on FTY-002: %+v", q[1])
	}
	if !q[2].Tripped() || q[2].Attempts != 3 {
		t.Errorf("FTY-004 should be tripped with 3 attempts: %+v", q[2])
	}
	if q[2].Assignable() {
		t.Errorf("a needs_attention story must not be assignable")
	}
}
