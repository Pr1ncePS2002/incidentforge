package config // import "miniflux.app/v2/internal/config"

import (
	"os"
	"path/filepath"
	"testing"
)

func forgeRTWriteFile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "miniflux.conf")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func forgeRTReadFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func forgeRTCountEntries(t *testing.T, dir string) int {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	return len(entries)
}

func forgeRTExpectRejected(t *testing.T, set map[string]string, unset []string) {
	t.Helper()
	const original = "# keep\nLOG_LEVEL=debug\nCUSTOM_OPERATOR_KEY=1\n"
	path := forgeRTWriteFile(t, original)
	if err := UpdateConfigFile(path, set, unset); err == nil {
		t.Fatalf("expected an error for set=%q unset=%q", set, unset)
	}
	if got := forgeRTReadFile(t, path); got != original {
		t.Fatalf("a rejected update must leave the file untouched, got %q", got)
	}
	if n := forgeRTCountEntries(t, filepath.Dir(path)); n != 1 {
		t.Fatalf("a rejected update must not leave temporary files behind, found %d entries", n)
	}
}

func TestFaultDroppedFieldUnknownKeysAndComments(t *testing.T) {
	original := "# Miniflux configuration\nLOG_LEVEL=debug\n\nCUSTOM_OPERATOR_KEY=keep-me\n   # indented comment\nLISTEN_ADDR=127.0.0.1:8080\n"
	path := forgeRTWriteFile(t, original)
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "warning"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "# Miniflux configuration\nLOG_LEVEL=warning\n\nCUSTOM_OPERATOR_KEY=keep-me\n   # indented comment\nLISTEN_ADDR=127.0.0.1:8080\n"
	if got := forgeRTReadFile(t, path); got != want {
		t.Fatalf("only LOG_LEVEL may change\nwant %q\ngot  %q", want, got)
	}
	if _, err := NewConfigParser().ParseFile(path); err != nil {
		t.Fatalf("updated file must still load: %v", err)
	}
}

func TestFaultDroppedFieldUnsetKeepsOthers(t *testing.T) {
	path := forgeRTWriteFile(t, "A_CUSTOM=1\nLOG_LEVEL=debug\nB_CUSTOM=2\n")
	if err := UpdateConfigFile(path, nil, []string{"LOG_LEVEL"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "A_CUSTOM=1\nB_CUSTOM=2\n" {
		t.Fatalf("unset must remove only LOG_LEVEL, got %q", got)
	}
}

func TestFaultDefaultOverwriteExplicitDefaultValue(t *testing.T) {
	path := forgeRTWriteFile(t, "LISTEN_ADDR=127.0.0.1:8080\n")
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "info"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "LISTEN_ADDR=127.0.0.1:8080\nLOG_LEVEL=info\n"
	if got := forgeRTReadFile(t, path); got != want {
		t.Fatalf("a value equal to the default must be written explicitly\nwant %q\ngot  %q", want, got)
	}
}

func TestFaultDefaultOverwriteExplicitEmptyValue(t *testing.T) {
	path := forgeRTWriteFile(t, "ADMIN_USERNAME=admin\nLOG_LEVEL=debug\n")
	if err := UpdateConfigFile(path, map[string]string{"ADMIN_USERNAME": ""}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "ADMIN_USERNAME=\nLOG_LEVEL=debug\n" {
		t.Fatalf("an explicit empty value must be kept as KEY=, got %q", got)
	}
	if err := UpdateConfigFile(path, nil, []string{"ADMIN_USERNAME"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "LOG_LEVEL=debug\n" {
		t.Fatalf("unset must remove the key entirely, got %q", got)
	}
}

func TestFaultDefaultOverwriteExplicitEmptyNewKey(t *testing.T) {
	path := forgeRTWriteFile(t, "LOG_LEVEL=debug\n")
	if err := UpdateConfigFile(path, map[string]string{"ADMIN_USERNAME": ""}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "LOG_LEVEL=debug\nADMIN_USERNAME=\n" {
		t.Fatalf("an explicit empty value for a new key must be appended as KEY=, got %q", got)
	}
}

func TestFaultPartialWriteLineBreakInjection(t *testing.T) {
	forgeRTExpectRejected(t, map[string]string{"LOG_LEVEL": "info\nCREATE_ADMIN=1"}, nil)
	forgeRTExpectRejected(t, map[string]string{"LOG_LEVEL": "info\r"}, nil)
}

func TestFaultPartialWriteInvalidKeys(t *testing.T) {
	forgeRTExpectRejected(t, map[string]string{"BAD KEY": "1"}, nil)
	forgeRTExpectRejected(t, map[string]string{"A=B": "1"}, nil)
	forgeRTExpectRejected(t, map[string]string{"": "1"}, nil)
	forgeRTExpectRejected(t, nil, []string{"LOG LEVEL"})
}

func TestFaultPartialWriteUnrepresentableValue(t *testing.T) {
	forgeRTExpectRejected(t, map[string]string{"LOG_LEVEL": " info"}, nil)
	forgeRTExpectRejected(t, map[string]string{"LOG_LEVEL": "info "}, nil)
}

func TestFaultPartialWriteConflictingChange(t *testing.T) {
	forgeRTExpectRejected(t, map[string]string{"LOG_LEVEL": "info", "CUSTOM_X": "1"}, []string{"LOG_LEVEL"})
}

func TestConfigFileNoChangeIsByteIdentical(t *testing.T) {
	original := "# header\n  LOG_LEVEL = debug  \n\nCUSTOM_THING=x\nLISTEN_ADDR=127.0.0.1:8080"
	path := forgeRTWriteFile(t, original)
	if err := UpdateConfigFile(path, nil, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != original {
		t.Fatalf("no-op update changed the file: %q", got)
	}
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "debug"}, []string{"NOT_PRESENT"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != original {
		t.Fatalf("setting an identical value must keep the original line, got %q", got)
	}
}

func TestConfigFileChangeWithoutTrailingNewline(t *testing.T) {
	path := forgeRTWriteFile(t, "CUSTOM_THING=x\nLOG_LEVEL=debug")
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "error"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "CUSTOM_THING=x\nLOG_LEVEL=error" {
		t.Fatalf("absence of a final newline must be preserved, got %q", got)
	}
}

func TestConfigFileDuplicateKeysCollapse(t *testing.T) {
	path := forgeRTWriteFile(t, "LOG_LEVEL=debug\nCUSTOM_FOO=1\nLOG_LEVEL=error\n")
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "warning"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "LOG_LEVEL=warning\nCUSTOM_FOO=1\n" {
		t.Fatalf("duplicates must collapse onto the first occurrence, got %q", got)
	}
}

func TestConfigFileNewKeysAppendedSorted(t *testing.T) {
	path := forgeRTWriteFile(t, "# only a comment\n")
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "debug", "ADMIN_USERNAME": "admin"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "# only a comment\nADMIN_USERNAME=admin\nLOG_LEVEL=debug\n"
	if got := forgeRTReadFile(t, path); got != want {
		t.Fatalf("want %q, got %q", want, got)
	}
}

func TestConfigFileMissingFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "miniflux.conf")
	if err := UpdateConfigFile(path, nil, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("a no-op update must not create the file, stat err=%v", err)
	}
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "debug"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := forgeRTReadFile(t, path); got != "LOG_LEVEL=debug\n" {
		t.Fatalf("unexpected content %q", got)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o600 {
		t.Fatalf("new file must be 0600, got %o", perm)
	}
	if n := forgeRTCountEntries(t, dir); n != 1 {
		t.Fatalf("expected only the config file in the directory, found %d entries", n)
	}
	if _, err := NewConfigParser().ParseFile(path); err != nil {
		t.Fatalf("created file must load: %v", err)
	}
}

func TestConfigFilePermissionsPreserved(t *testing.T) {
	path := forgeRTWriteFile(t, "LOG_LEVEL=debug\n")
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}
	if err := UpdateConfigFile(path, map[string]string{"LOG_LEVEL": "info"}, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o640 {
		t.Fatalf("permissions must be preserved, got %o", perm)
	}
}
