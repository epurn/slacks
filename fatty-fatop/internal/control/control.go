// Package control is fatop's ONLY mutating surface. Everything else (internal/state)
// is read-only. This edits the steward's .env and signals it to hot-reload, so
// the operator can tune live config (parallelism, poll interval) from the TUI
// without restarting the agent. It never touches the public fatty repo.
package control

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
)

// Knob is one live-editable steward setting.
type Knob struct {
	Key   string // env var, e.g. FATTY_STEWARD_MAX_AUTHORS
	Label string
	Def   int    // default when unset in .env
	Min   int
	Max   int
	Help  string
}

// Knobs is the live-tunable set surfaced in the fatop config view. All are read
// by the steward from os.environ each poll cycle, so a hot-reload applies them on
// the next poll.
var Knobs = []Knob{
	{Key: "FATTY_STEWARD_MAX_AUTHORS", Label: "max authors", Def: 2, Min: 0, Max: 8, Help: "concurrent author runs"},
	{Key: "FATTY_STEWARD_MAX_REVIEWERS", Label: "max reviewers", Def: 2, Min: 0, Max: 8, Help: "concurrent PR reviews"},
	{Key: "FATTY_STEWARD_MAX_REPAIRS", Label: "max repairs", Def: 1, Min: 0, Max: 4, Help: "concurrent auto-repairs"},
	{Key: "FATTY_STEWARD_INTERVAL_SECONDS", Label: "poll interval", Def: 180, Min: 30, Max: 1800, Help: "seconds between polls"},
}

// Clamp keeps v within the knob's range.
func (k Knob) Clamp(v int) int {
	if v < k.Min {
		return k.Min
	}
	if v > k.Max {
		return k.Max
	}
	return v
}

// ReadInt returns the current value of key from the .env file, or def if it is
// unset or unparseable.
func ReadInt(envPath, key string, def int) int {
	data, err := os.ReadFile(envPath)
	if err != nil {
		return def
	}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "#") || !strings.HasPrefix(line, key+"=") {
			continue
		}
		val := strings.TrimSpace(strings.TrimPrefix(line, key+"="))
		val = strings.Trim(val, `"'`)
		if n, err := strconv.Atoi(val); err == nil {
			return n
		}
	}
	return def
}

// SetInt updates (or appends) key=val in the .env file, preserving other lines.
func SetInt(envPath, key string, val int) error {
	data, _ := os.ReadFile(envPath) // missing file → create with just this key
	lines := strings.Split(string(data), "\n")
	repl := fmt.Sprintf("%s=%d", key, val)
	found := false
	for i, line := range lines {
		if strings.HasPrefix(strings.TrimSpace(line), key+"=") {
			lines[i] = repl
			found = true
			break
		}
	}
	if !found {
		// Append, keeping a single trailing newline.
		if len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "" {
			lines[len(lines)-1] = repl
			lines = append(lines, "")
		} else {
			lines = append(lines, repl, "")
		}
	}
	return os.WriteFile(envPath, []byte(strings.Join(lines, "\n")), 0o600)
}

// SignalReload finds the running steward and sends it SIGHUP so it re-reads .env
// on its next poll. Returns an error if no process matched.
func SignalReload() error {
	out, err := exec.Command("pgrep", "-f", "steward_agent/runner.py").Output()
	if err != nil {
		return fmt.Errorf("steward not running")
	}
	signalled := 0
	for _, ln := range strings.Fields(string(out)) {
		pid, err := strconv.Atoi(ln)
		if err != nil {
			continue
		}
		if syscall.Kill(pid, syscall.SIGHUP) == nil {
			signalled++
		}
	}
	if signalled == 0 {
		return fmt.Errorf("could not signal steward")
	}
	return nil
}

// Apply writes a knob's value to .env and hot-reloads the steward.
func Apply(envPath, key string, val int) error {
	if err := SetInt(envPath, key, val); err != nil {
		return fmt.Errorf("write .env: %w", err)
	}
	return SignalReload()
}
