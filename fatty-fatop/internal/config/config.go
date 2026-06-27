// Package config resolves the on-disk layout of the Fatty command centre so the
// rest of fatop can find logs, run-state, and event streams. Everything here is
// private command-centre tooling; nothing fatop reads belongs in public fatty.
package config

import (
	"os"
	"path/filepath"
)

// DefaultRoot is the command-centre root used when nothing else is specified.
const DefaultRoot = "/Users/epurn/workspace/fatty-suite"

// Paths holds every location fatop reads from.
type Paths struct {
	Root string

	StewardLog    string // human text log (out)
	StewardErr    string
	StewardEvents string // structured JSONL

	ReviewerLog    string
	ReviewerErr    string
	ReviewerEvents string

	AuthorEvents string // service-level author events

	RunDir     string // fatty-worktrees/.steward-run
	Repo       string // GitHub repo, e.g. epurn/fatty
	Roadmap    string // docs/stories/v1-roadmap.md (the steward's story queue)
	StoriesDir string // docs/stories/
	StewardEnv string // fatty-steward-agent/.env (live-editable config)
}

// Resolve picks the command-centre root using, in order: an explicit root
// argument, the FATTY_HOME env var, an upward search from the working directory,
// then DefaultRoot. It then derives all dependent paths.
func Resolve(root string) Paths {
	if root == "" {
		root = os.Getenv("FATTY_HOME")
	}
	if root == "" {
		if found, ok := searchUp(); ok {
			root = found
		}
	}
	if root == "" {
		root = DefaultRoot
	}

	repo := os.Getenv("FATTY_STEWARD_REPO")
	if repo == "" {
		repo = "epurn/fatty"
	}

	runDir := os.Getenv("FATTY_STEWARD_RUN_DIR")
	if runDir == "" {
		runDir = filepath.Join(root, "fatty-worktrees", ".steward-run")
	}

	return Paths{
		Root:           root,
		StewardLog:     filepath.Join(root, "fatty-steward-agent", "logs", "steward.out.log"),
		StewardErr:     filepath.Join(root, "fatty-steward-agent", "logs", "steward.err.log"),
		StewardEvents:  filepath.Join(root, "fatty-steward-agent", "logs", "steward.events.jsonl"),
		ReviewerLog:    filepath.Join(root, "fatty-reviewer-agent", "logs", "reviewer.out.log"),
		ReviewerErr:    filepath.Join(root, "fatty-reviewer-agent", "logs", "reviewer.err.log"),
		ReviewerEvents: filepath.Join(root, "fatty-reviewer-agent", "logs", "reviewer.events.jsonl"),
		AuthorEvents:   filepath.Join(root, "fatty-author-agent", "logs", "author.events.jsonl"),
		RunDir:         runDir,
		Repo:           repo,
		Roadmap:        filepath.Join(root, "docs", "stories", "v1-roadmap.md"),
		StoriesDir:     filepath.Join(root, "docs", "stories"),
		StewardEnv:     filepath.Join(root, "fatty-steward-agent", ".env"),
	}
}

// AgentEvents returns the structured event file for a named agent, or "".
func (p Paths) AgentEvents(agent string) string {
	switch agent {
	case "steward":
		return p.StewardEvents
	case "reviewer":
		return p.ReviewerEvents
	case "author":
		return p.AuthorEvents
	}
	return ""
}

// searchUp walks up from the working directory looking for a directory that
// contains a fatty-worktrees folder, treating that as the command-centre root.
func searchUp() (string, bool) {
	dir, err := os.Getwd()
	if err != nil {
		return "", false
	}
	for {
		if st, err := os.Stat(filepath.Join(dir, "fatty-worktrees")); err == nil && st.IsDir() {
			return dir, true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", false
		}
		dir = parent
	}
}
