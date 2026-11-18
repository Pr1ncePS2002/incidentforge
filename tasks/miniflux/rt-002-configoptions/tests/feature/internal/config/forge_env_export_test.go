package config // import "miniflux.app/v2/internal/config"

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func forgeExportWrite(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "miniflux.conf")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func forgeExportRead(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func forgeExportEntries(t *testing.T, dir string) int {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	return len(entries)
}

func TestFaultDroppedFieldUnknownKeysAndCommentsKept(t *testing.T) {
	original := "# Miniflux settings\nCUSTOM_UNKNOWN_SETTING=keep-me\n\nLOG_LEVEL=debug\nPOLLING_FREQUENCY=30\nRUN_MIGRATIONS=yes\n"
	path := forgeExportWrite(t, original)

	if err := ExportEnvironmentToFile(path, []string{"PATH=/usr/bin", "HOME=/tmp", "POLLING_FREQUENCY=15"}); err != nil {
		t.Fatalf("export failed: %v", err)
	}

	want := "# Miniflux settings\nCUSTOM_UNKNOWN_SETTING=keep-me\n\nLOG_LEVEL=debug\nPOLLING_FREQUENCY=15\nRUN_MIGRATIONS=yes\n"
	if got := forgeExportRead(t, path); got != want {
		t.Fatalf("unexpected file content:\n got: %q\nwant: %q", got, want)
	}
}

func TestFaultDefaultOverwriteExplicitValuesWritten(t *testing.T) {
	path := filepath.Join(t.TempDir(), "miniflux.conf")

	err := ExportEnvironmentToFile(path, []string{"POLLING_FREQUENCY=60", "OAUTH2_CLIENT_ID=", "LOG_LEVEL=info", "PATH=/bin"})
	if err != nil {
		t.Fatalf("export failed: %v", err)
	}

	want := "LOG_LEVEL=info\nOAUTH2_CLIENT_ID=\nPOLLING_FREQUENCY=60\n"
	if got := forgeExportRead(t, path); got != want {
		t.Fatalf("default-valued and empty settings must be written explicitly:\n got: %q\nwant: %q", got, want)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("new configuration file must be created with mode 0600, got %v", info.Mode().Perm())
	}
}

func TestFaultDefaultOverwriteExplicitEmptyReplacesValue(t *testing.T) {
	path := forgeExportWrite(t, "LOG_LEVEL=debug\nOAUTH2_CLIENT_ID=abc\n")

	if err := ExportEnvironmentToFile(path, []string{"OAUTH2_CLIENT_ID="}); err != nil {
		t.Fatalf("export failed: %v", err)
	}

	want := "LOG_LEVEL=debug\nOAUTH2_CLIENT_ID=\n"
	if got := forgeExportRead(t, path); got != want {
		t.Fatalf("an explicitly empty value must be kept as KEY=:\n got: %q\nwant: %q", got, want)
	}
}

func TestFaultTypeDriftValuesWrittenVerbatim(t *testing.T) {
	path := forgeExportWrite(t, "RUN_MIGRATIONS=1\nPOLLING_FREQUENCY=30\n")

	if err := ExportEnvironmentToFile(path, []string{"RUN_MIGRATIONS=yes", "CLEANUP_ARCHIVE_READ_DAYS=60"}); err != nil {
		t.Fatalf("export failed: %v", err)
	}

	want := "RUN_MIGRATIONS=yes\nPOLLING_FREQUENCY=30\nCLEANUP_ARCHIVE_READ_DAYS=60\n"
	if got := forgeExportRead(t, path); got != want {
		t.Fatalf("values must be written verbatim:\n got: %q\nwant: %q", got, want)
	}
}

func TestFaultPartialWriteKeepsPreviousFile(t *testing.T) {
	original := "LOG_LEVEL=debug\nPOLLING_FREQUENCY=30\n"
	path := forgeExportWrite(t, original)

	err := ExportEnvironmentToFile(path, []string{"POLLING_FREQUENCY=15", "LOG_LEVEL=info\nRUN_MIGRATIONS=0"})
	if err == nil {
		t.Fatal("expected an error for a value containing a line break")
	}
	if !strings.Contains(err.Error(), "LOG_LEVEL") {
		t.Errorf("error should name LOG_LEVEL, got %q", err)
	}
	if got := forgeExportRead(t, path); got != original {
		t.Fatalf("a failed export must leave the previous file intact:\n got: %q\nwant: %q", got, original)
	}
	if n := forgeExportEntries(t, filepath.Dir(path)); n != 1 {
		t.Fatalf("a failed export must not leave temporary files behind, found %d entries", n)
	}
}

func TestExportWithoutChangesLeavesFileIdentical(t *testing.T) {
	original := "# comment\nLOG_LEVEL = debug\r\nPOLLING_FREQUENCY=30"
	path := forgeExportWrite(t, original)

	if err := ExportEnvironmentToFile(path, []string{"LOG_LEVEL=debug", "POLLING_FREQUENCY=30", "PATH=/bin"}); err != nil {
		t.Fatalf("export failed: %v", err)
	}
	if got := forgeExportRead(t, path); got != original {
		t.Fatalf("an export without changes must be a no-op:\n got: %q\nwant: %q", got, original)
	}

	if err := ExportEnvironmentToFile(path, nil); err != nil {
		t.Fatalf("export of an empty environment failed: %v", err)
	}
	if got := forgeExportRead(t, path); got != original {
		t.Fatalf("an empty environment must not change the file:\n got: %q\nwant: %q", got, original)
	}
}

func TestExportAppendsAfterMissingTrailingNewline(t *testing.T) {
	path := forgeExportWrite(t, "LOG_LEVEL=debug")

	if err := ExportEnvironmentToFile(path, []string{"POLLING_FREQUENCY=15"}); err != nil {
		t.Fatalf("export failed: %v", err)
	}
	want := "LOG_LEVEL=debug\nPOLLING_FREQUENCY=15\n"
	if got := forgeExportRead(t, path); got != want {
		t.Fatalf("unexpected file content:\n got: %q\nwant: %q", got, want)
	}
}

func TestExportKeepsFileModeAndParses(t *testing.T) {
	path := forgeExportWrite(t, "LOG_LEVEL=debug\n")
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}

	if err := ExportEnvironmentToFile(path, []string{"LOG_LEVEL=info", "POLLING_FREQUENCY=15"}); err != nil {
		t.Fatalf("export failed: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o640 {
		t.Fatalf("file mode must be preserved, got %v", info.Mode().Perm())
	}
	if n := forgeExportEntries(t, filepath.Dir(path)); n != 1 {
		t.Fatalf("no temporary files may remain, found %d entries", n)
	}
	if _, err := NewConfigParser().ParseFile(path); err != nil {
		t.Fatalf("exported file must be loadable: %v", err)
	}
}
