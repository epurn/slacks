package state

import (
	"bufio"
	"encoding/json"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Event is one line of the structured agent event log (see
// docs/agent-event-log.md).
type Event struct {
	Ts     time.Time
	TsRaw  string
	Agent  string
	RunID  string
	Level  string
	EventT string // the "event" field; named EventT to avoid colliding with type
	Msg    string
	Fields map[string]any
}

type rawEvent struct {
	Ts     string         `json:"ts"`
	Agent  string         `json:"agent"`
	RunID  string         `json:"run_id"`
	Level  string         `json:"level"`
	Event  string         `json:"event"`
	Msg    string         `json:"msg"`
	Fields map[string]any `json:"fields"`
}

// ParseEventLine parses one JSONL envelope line. ok is false for blank or
// malformed lines, which callers should silently skip.
func ParseEventLine(line string) (Event, bool) {
	line = strings.TrimSpace(line)
	if line == "" || line[0] != '{' {
		return Event{}, false
	}
	var r rawEvent
	if err := json.Unmarshal([]byte(line), &r); err != nil {
		return Event{}, false
	}
	ev := Event{
		TsRaw:  r.Ts,
		Agent:  r.Agent,
		RunID:  r.RunID,
		Level:  r.Level,
		EventT: r.Event,
		Msg:    r.Msg,
		Fields: r.Fields,
	}
	if t, err := time.Parse(time.RFC3339, strings.Replace(r.Ts, "Z", "+00:00", 1)); err == nil {
		ev.Ts = t
	} else if t, err := time.Parse(time.RFC3339Nano, r.Ts); err == nil {
		ev.Ts = t
	}
	if ev.Fields == nil {
		ev.Fields = map[string]any{}
	}
	return ev, true
}

// Field returns a string view of a fields entry, or "".
func (e Event) Field(key string) string {
	v, ok := e.Fields[key]
	if !ok || v == nil {
		return ""
	}
	switch t := v.(type) {
	case string:
		return t
	case float64:
		// JSON numbers decode as float64; render whole numbers without ".0".
		if t == float64(int64(t)) {
			return strconv.FormatInt(int64(t), 10)
		}
		return strconv.FormatFloat(t, 'f', -1, 64)
	case bool:
		if t {
			return "true"
		}
		return "false"
	default:
		b, _ := json.Marshal(t)
		return string(b)
	}
}

// FieldFloat returns a numeric fields entry as a float64. JSON numbers decode as
// float64; numeric strings are parsed as a fallback. ok is false when the key is
// absent or non-numeric.
func (e Event) FieldFloat(key string) (float64, bool) {
	v, ok := e.Fields[key]
	if !ok || v == nil {
		return 0, false
	}
	switch t := v.(type) {
	case float64:
		return t, true
	case int:
		return float64(t), true
	case int64:
		return float64(t), true
	case string:
		if f, err := strconv.ParseFloat(t, 64); err == nil {
			return f, true
		}
	}
	return 0, false
}

// FieldInt returns a numeric fields entry as an int64 (truncating any fraction).
func (e Event) FieldInt(key string) (int64, bool) {
	f, ok := e.FieldFloat(key)
	if !ok {
		return 0, false
	}
	return int64(f), true
}

// ReadEvents reads up to the last `max` events from a JSONL file. A max of 0
// means no limit. Missing files yield an empty slice and no error.
func ReadEvents(path string, max int) ([]Event, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()

	var out []Event
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for sc.Scan() {
		if ev, ok := ParseEventLine(sc.Text()); ok {
			out = append(out, ev)
		}
	}
	if err := sc.Err(); err != nil {
		return out, err
	}
	if max > 0 && len(out) > max {
		out = out[len(out)-max:]
	}
	return out, nil
}

// MergeEvents reads several event files and returns them sorted by timestamp
// ascending, keeping at most `max` of the most recent (0 = no limit).
func MergeEvents(paths []string, max int) []Event {
	var all []Event
	for _, p := range paths {
		evs, _ := ReadEvents(p, 0)
		all = append(all, evs...)
	}
	sort.SliceStable(all, func(i, j int) bool {
		if all[i].Ts.Equal(all[j].Ts) {
			return all[i].TsRaw < all[j].TsRaw
		}
		return all[i].Ts.Before(all[j].Ts)
	})
	if max > 0 && len(all) > max {
		all = all[len(all)-max:]
	}
	return all
}
