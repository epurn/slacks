package state

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// QueueStory is one row of the steward's story roadmap, annotated with the
// dependency / activity state that decides whether the steward can assign it
// next. fatop reads the same roadmap + run-state the steward routes off, so the
// queue view mirrors what the steward will actually do.
type QueueStory struct {
	ID        string
	State     string   // ready | ready_with_notes | needs_attention | ...
	Lane      string
	Title     string
	Deps      []string // every story this one depends on
	UnmetDeps []string // deps not yet merged
	Active    bool     // an author is currently running it
	Attempts  int      // circuit-breaker implement-attempt count
}

// Ready reports whether the steward considers the story assignable by state.
func (q QueueStory) Ready() bool { return q.State == "ready" || q.State == "ready_with_notes" }

// Tripped reports whether the circuit breaker pulled the story.
func (q QueueStory) Tripped() bool { return q.State == "needs_attention" }

// Blocked reports a ready story held back only by unmet dependencies.
func (q QueueStory) Blocked() bool { return q.Ready() && len(q.UnmetDeps) > 0 }

// Assignable reports a ready story the steward could pick up right now (deps met,
// not already running). Lane contention is dynamic and left to the steward.
func (q QueueStory) Assignable() bool { return q.Ready() && len(q.UnmetDeps) == 0 && !q.Active }

var (
	roadmapRow  = regexp.MustCompile(`^\|\s*(FTY-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$`)
	mdLink      = regexp.MustCompile(`\[([^\]]*)\]\(([^)]+)\)`)
	ftyRef      = regexp.MustCompile(`FTY-\d+`)
	depsSection = regexp.MustCompile(`(?s)## Dependencies\s*\n(.*?)(?:\n## |$)`)
	approvedKey = regexp.MustCompile(`(?m)^approved_dependencies:.*(?:\n(?:\s+-\s+.*)?)*`)
)

var mergedStates = map[string]bool{"merged": true, "done": true, "complete": true, "completed": true}

// LoadQueue parses the roadmap and returns the actionable queue — ready and
// circuit-tripped stories in roadmap (assignment) order — with each story's
// dependency, activity, and attempt state resolved. Merged/candidate rows are
// omitted. Missing roadmap → empty, no error.
func LoadQueue(roadmapPath, storiesDir, runDir string) ([]QueueStory, error) {
	data, err := os.ReadFile(roadmapPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	// First pass: every row's state, to compute the merged set.
	type row struct{ id, state, lane, title, file string }
	var rows []row
	merged := mergedRunIDs(runDir)
	for _, line := range strings.Split(string(data), "\n") {
		m := roadmapRow.FindStringSubmatch(strings.TrimRight(line, "\r"))
		if m == nil {
			continue
		}
		id, st := strings.TrimSpace(m[1]), strings.TrimSpace(m[2])
		if id == "ID" {
			continue
		}
		file := ""
		if link := mdLink.FindStringSubmatch(m[4]); link != nil {
			file = link[2]
		}
		rows = append(rows, row{id: id, state: st, lane: strings.TrimSpace(m[3]), title: linkText(m[4]), file: file})
		if mergedStates[st] {
			merged[id] = true
		}
	}

	attempts := loadAttemptsMap(runDir)
	active := activeMarkerIDs(runDir)

	var out []QueueStory
	for _, r := range rows {
		q := QueueStory{ID: r.id, State: r.state, Lane: r.lane, Title: r.title}
		if !q.Ready() && !q.Tripped() {
			continue // merged / candidate — not part of the actionable queue
		}
		q.Active = active[r.id]
		q.Attempts = attempts[r.id]
		if r.file != "" {
			q.Deps = storyDeps(filepath.Join(storiesDir, r.file), r.id)
			for _, d := range q.Deps {
				if !merged[d] {
					q.UnmetDeps = append(q.UnmetDeps, d)
				}
			}
		}
		out = append(out, q)
	}
	return out, nil
}

func linkText(cell string) string {
	if link := mdLink.FindStringSubmatch(cell); link != nil {
		return strings.TrimSpace(link[1])
	}
	return strings.TrimSpace(cell)
}

// storyDeps parses the dependency ids the steward enforces: the front-matter
// approved_dependencies plus the "## Dependencies" section. Mirrors the
// steward's metadata_dependencies so the queue view matches routing.
func storyDeps(path, selfID string) []string {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	content := string(data)
	var refs []string
	if strings.HasPrefix(content, "---") {
		if end := strings.Index(content[3:], "\n---"); end != -1 {
			header := content[3 : 3+end]
			if block := approvedKey.FindString(header); block != "" {
				refs = append(refs, ftyRef.FindAllString(block, -1)...)
			}
		}
	}
	if sec := depsSection.FindStringSubmatch(content); sec != nil {
		refs = append(refs, ftyRef.FindAllString(sec[1], -1)...)
	}
	seen := map[string]bool{selfID: true}
	var out []string
	for _, r := range refs {
		if !seen[r] {
			seen[r] = true
			out = append(out, r)
		}
	}
	return out
}

func mergedRunIDs(runDir string) map[string]bool {
	out := map[string]bool{}
	data, err := os.ReadFile(filepath.Join(runDir, "merged-stories.json"))
	if err != nil {
		return out
	}
	var ids []string
	if json.Unmarshal(data, &ids) == nil {
		for _, id := range ids {
			out[id] = true
		}
	}
	return out
}

func loadAttemptsMap(runDir string) map[string]int {
	out := map[string]int{}
	data, err := os.ReadFile(filepath.Join(runDir, "attempts.json"))
	if err != nil {
		return out
	}
	raw := map[string]json.Number{}
	if json.Unmarshal(data, &raw) == nil {
		for id, n := range raw {
			if v, err := n.Int64(); err == nil {
				out[id] = int(v)
			}
		}
	}
	return out
}

func activeMarkerIDs(runDir string) map[string]bool {
	out := map[string]bool{}
	entries, err := os.ReadDir(runDir)
	if err != nil {
		return out
	}
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".active") {
			out[strings.TrimSuffix(e.Name(), ".active")] = true
		}
	}
	return out
}
