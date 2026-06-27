package state

import (
	"os/exec"
	"strings"
)

// Service describes one agent process. Only the steward is always-on; the author
// and reviewer are one-shot workers the steward dispatches, so "not running" is
// their normal idle state, not a fault.
type Service struct {
	Name     string
	Up       bool
	OnDemand bool   // dispatched per-task; down ≠ unhealthy
	Detail   string // pid list or status hint
}

var onDemandAgents = map[string]bool{"author": true, "reviewer": true}

var serviceProcPatterns = map[string]string{
	"steward":  "steward_agent/runner.py",
	"reviewer": "reviewer_agent/runner.py",
	"author":   "author_agent/runner.py",
}

// LoadServices reports whether each agent process is currently running by
// matching the runner command line via pgrep. The author is one-shot, so it is
// frequently (and correctly) down.
func LoadServices() []Service {
	order := []string{"steward", "reviewer", "author"}
	out := make([]Service, 0, len(order))
	for _, name := range order {
		pattern := serviceProcPatterns[name]
		pids := pgrep(pattern)
		svc := Service{Name: name, Up: len(pids) > 0, OnDemand: onDemandAgents[name]}
		switch {
		case svc.Up:
			svc.Detail = "pid " + strings.Join(pids, ",")
		case svc.OnDemand:
			svc.Detail = "on-demand (idle)"
		default:
			svc.Detail = "not running"
		}
		out = append(out, svc)
	}
	return out
}

func pgrep(pattern string) []string {
	cmd := exec.Command("pgrep", "-f", pattern)
	data, err := cmd.Output()
	if err != nil {
		return nil
	}
	var pids []string
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			pids = append(pids, line)
		}
	}
	return pids
}
