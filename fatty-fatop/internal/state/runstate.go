package state

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Run is one author assignment tracked in the steward run directory.
type Run struct {
	ID         string   // story id or PR-<n>
	Mode       string   // implement | fix-pr
	Story      string   // story_id from the assignment
	Lanes      []string // changed-file areas
	Repo       string
	Active     bool      // a .active marker is present
	StartedAt  time.Time // marker mtime (best-effort start time)
	LogPath    string    // <id>.log  (human console)
	EventsPath string    // <id>.events.jsonl (claude stream)
	Worktree   string
}

// Age returns how long an active run has been going, or 0 if not active.
func (r Run) Age() time.Duration {
	if !r.Active || r.StartedAt.IsZero() {
		return 0
	}
	return time.Since(r.StartedAt)
}

type assignmentFile struct {
	StoryID  string   `json:"story_id"`
	Mode     string   `json:"mode"`
	Lanes    []string `json:"lanes"`
	Repo     string   `json:"repo"`
	Worktree string   `json:"worktree"`
}

// LoadRuns scans the steward run directory and returns one Run per assignment
// JSON, newest-active first.
func LoadRuns(runDir string) ([]Run, error) {
	entries, err := os.ReadDir(runDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	var runs []Run
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".json") {
			continue
		}
		// Steward bookkeeping, not an author assignment: a JSON array of merged
		// story ids. Skip by name (and the generic parse guard below also catches
		// it) so it never renders as a phantom idle run.
		if name == "merged-stories.json" {
			continue
		}
		id := strings.TrimSuffix(name, ".json")
		jsonPath := filepath.Join(runDir, name)
		data, err := os.ReadFile(jsonPath)
		if err != nil {
			continue
		}
		var a assignmentFile
		if err := json.Unmarshal(data, &a); err != nil {
			// Not a valid assignment object (e.g. a bookkeeping array) — not a run.
			continue
		}

		run := Run{
			ID:         id,
			Mode:       a.Mode,
			Story:      a.StoryID,
			Lanes:      a.Lanes,
			Repo:       a.Repo,
			Worktree:   a.Worktree,
			LogPath:    filepath.Join(runDir, id+".log"),
			EventsPath: filepath.Join(runDir, id+".events.jsonl"),
		}
		if run.Mode == "" {
			if strings.HasPrefix(id, "PR-") {
				run.Mode = "fix-pr"
			} else {
				run.Mode = "implement"
			}
		}
		if marker := filepath.Join(runDir, id+".active"); fileExists(marker) {
			run.Active = true
			if st, err := os.Stat(marker); err == nil {
				run.StartedAt = st.ModTime()
			}
		}
		runs = append(runs, run)
	}

	sort.SliceStable(runs, func(i, j int) bool {
		if runs[i].Active != runs[j].Active {
			return runs[i].Active // active first
		}
		return runs[i].StartedAt.After(runs[j].StartedAt)
	})
	return runs, nil
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
