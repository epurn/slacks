package control

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestReadSetInt(t *testing.T) {
	dir := t.TempDir()
	env := filepath.Join(dir, ".env")
	os.WriteFile(env, []byte("# comment\nFATTY_STEWARD_MAX_AUTHORS=2\nOTHER=keep\n"), 0o600)

	if got := ReadInt(env, "FATTY_STEWARD_MAX_AUTHORS", 9); got != 2 {
		t.Fatalf("ReadInt = %d, want 2", got)
	}
	if got := ReadInt(env, "FATTY_STEWARD_MAX_REVIEWERS", 5); got != 5 {
		t.Fatalf("ReadInt default = %d, want 5", got)
	}

	// Update existing key, preserve others.
	if err := SetInt(env, "FATTY_STEWARD_MAX_AUTHORS", 4); err != nil {
		t.Fatal(err)
	}
	if got := ReadInt(env, "FATTY_STEWARD_MAX_AUTHORS", 0); got != 4 {
		t.Errorf("after SetInt = %d, want 4", got)
	}
	body, _ := os.ReadFile(env)
	if !strings.Contains(string(body), "OTHER=keep") {
		t.Error("SetInt clobbered other keys")
	}
	if strings.Count(string(body), "FATTY_STEWARD_MAX_AUTHORS=") != 1 {
		t.Error("SetInt duplicated the key")
	}

	// Append a new key.
	if err := SetInt(env, "FATTY_STEWARD_MAX_REPAIRS", 3); err != nil {
		t.Fatal(err)
	}
	if got := ReadInt(env, "FATTY_STEWARD_MAX_REPAIRS", 0); got != 3 {
		t.Errorf("appended key = %d, want 3", got)
	}
}

func TestClamp(t *testing.T) {
	k := Knob{Min: 0, Max: 8}
	if k.Clamp(-1) != 0 || k.Clamp(9) != 8 || k.Clamp(3) != 3 {
		t.Error("Clamp out of range")
	}
}

func TestSetIntCreatesFile(t *testing.T) {
	env := filepath.Join(t.TempDir(), ".env")
	if err := SetInt(env, "FATTY_STEWARD_MAX_AUTHORS", 1); err != nil {
		t.Fatal(err)
	}
	if got := ReadInt(env, "FATTY_STEWARD_MAX_AUTHORS", 0); got != 1 {
		t.Errorf("created file value = %d, want 1", got)
	}
}
