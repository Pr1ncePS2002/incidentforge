package config // import "miniflux.app/v2/internal/config"

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func forgeRenameFixture(t *testing.T, content string, perm os.FileMode) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "miniflux.conf")
	if err := os.WriteFile(path, []byte(content), perm); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, perm); err != nil {
		t.Fatal(err)
	}
	return path
}

func forgeRenameContent(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func forgeRenameDirEntries(t *testing.T, path string) []string {
	t.Helper()
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatal(err)
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	return names
}

func forgeRenameExpect(t *testing.T, renames map[string]string, input, want string) {
	t.Helper()
	path := forgeRenameFixture(t, input, 0o600)
	if err := RenameConfigKeys(path, renames); err != nil {
		t.Fatalf("RenameConfigKeys failed: %v", err)
	}
	if got := forgeRenameContent(t, path); got != want {
		t.Fatalf("unexpected content after rename\n got: %q\nwant: %q", got, want)
	}
	if names := forgeRenameDirEntries(t, path); len(names) != 1 {
		t.Fatalf("expected only the configuration file in its directory, got %v", names)
	}
}

func forgeRenameExpectRejected(t *testing.T, renames map[string]string, input string) {
	t.Helper()
	path := forgeRenameFixture(t, input, 0o640)
	if err := RenameConfigKeys(path, renames); err == nil {
		t.Fatalf("expected RenameConfigKeys(%v) to fail", renames)
	}
	if got := forgeRenameContent(t, path); got != input {
		t.Fatalf("a failed rename must keep the previous file\n got: %q\nwant: %q", got, input)
	}
	if names := forgeRenameDirEntries(t, path); len(names) != 1 {
		t.Fatalf("a failed rename must not leave extra files, got %v", names)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o640 {
		t.Fatalf("a failed rename must keep permissions, got %v", info.Mode().Perm())
	}
}

func TestRenameConfigKeysWithoutMatchIsNoop(t *testing.T) {
	input := "# Miniflux\r\nBASE_URL=http://reader.example/\n\n  POLLING_FREQUENCY = 60 \nUNKNOWN_FUTURE_KEY=abc"
	for _, renames := range []map[string]string{nil, {}, {"LEGACY_KEY": "NEW_KEY"}} {
		path := forgeRenameFixture(t, input, 0o600)
		past := time.Date(2020, time.January, 2, 3, 4, 5, 0, time.UTC)
		if err := os.Chtimes(path, past, past); err != nil {
			t.Fatal(err)
		}
		if err := RenameConfigKeys(path, renames); err != nil {
			t.Fatalf("RenameConfigKeys(%v) failed: %v", renames, err)
		}
		if got := forgeRenameContent(t, path); got != input {
			t.Fatalf("a rename without matches must not change the file\n got: %q\nwant: %q", got, input)
		}
		info, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		if !info.ModTime().Equal(past) {
			t.Fatalf("a rename without matches must not rewrite the file, mtime changed to %v", info.ModTime())
		}
	}
}

func TestRenameConfigKeysChangesOnlyTheRenamedKey(t *testing.T) {
	forgeRenameExpect(t,
		map[string]string{"LEGACY_ADMIN_USER": "ADMIN_USERNAME"},
		"CREATE_ADMIN=1\nLEGACY_ADMIN_USER=bob\nADMIN_PASSWORD=secret123\n",
		"CREATE_ADMIN=1\nADMIN_USERNAME=bob\nADMIN_PASSWORD=secret123\n",
	)
}

func TestRenamedConfigFileStillParses(t *testing.T) {
	path := forgeRenameFixture(t, "CREATE_ADMIN=1\nLEGACY_ADMIN_USER=bob\nADMIN_PASSWORD=secret123\n", 0o600)
	if err := RenameConfigKeys(path, map[string]string{"LEGACY_ADMIN_USER": "ADMIN_USERNAME"}); err != nil {
		t.Fatalf("RenameConfigKeys failed: %v", err)
	}
	parser := NewConfigParser()
	opts, err := parser.ParseFile(path)
	if err != nil {
		t.Fatalf("renamed file no longer parses: %v", err)
	}
	if !opts.CreateAdmin() {
		t.Error("CREATE_ADMIN was lost by the rename")
	}
	if opts.AdminUsername() != "bob" {
		t.Errorf("expected ADMIN_USERNAME=bob after rename, got %q", opts.AdminUsername())
	}
}

func TestFaultDroppedFieldCommentsAndUnknownKeys(t *testing.T) {
	forgeRenameExpect(t,
		map[string]string{"LEGACY_ADMIN_USER": "ADMIN_USERNAME"},
		"# Managed by ops\n\nLEGACY_ADMIN_USER=bob\n  # indented comment\nSOME_FUTURE_OPTION=keep me\nADMIN_PASSWORD=secret123\nTRAILING_KEY=last",
		"# Managed by ops\n\nADMIN_USERNAME=bob\n  # indented comment\nSOME_FUTURE_OPTION=keep me\nADMIN_PASSWORD=secret123\nTRAILING_KEY=last",
	)
}

func TestFaultDefaultOverwriteEmptyAndZeroValues(t *testing.T) {
	forgeRenameExpect(t,
		map[string]string{"OLD_PASSWORD": "ADMIN_PASSWORD", "OLD_FLAG": "CREATE_ADMIN", "OLD_SPACES": "SOME_OPTION"},
		"OLD_PASSWORD=\nOLD_FLAG=0\nOLD_SPACES=   \n",
		"ADMIN_PASSWORD=\nCREATE_ADMIN=0\nSOME_OPTION=   \n",
	)
}

func TestFaultTypeDriftRawValuesKept(t *testing.T) {
	forgeRenameExpect(t,
		map[string]string{"OLD_POLL": "POLLING_FREQUENCY", "OLD_LIST": "LIST_OPTION", "OLD_QUOTED": "QUOTED_OPTION", "OLD_NUMBER": "NUMBER_OPTION"},
		"  OLD_POLL = 1h30m  \r\nOLD_LIST=a, b ,c\nOLD_QUOTED=\"  x  \"\nOLD_NUMBER=007\n",
		"  POLLING_FREQUENCY = 1h30m  \r\nLIST_OPTION=a, b ,c\nQUOTED_OPTION=\"  x  \"\nNUMBER_OPTION=007\n",
	)
}

func TestFaultPartialWriteInvalidLineKeepsPreviousFile(t *testing.T) {
	forgeRenameExpectRejected(t,
		map[string]string{"LEGACY_ADMIN_USER": "ADMIN_USERNAME"},
		"LEGACY_ADMIN_USER=bob\nADMIN_PASSWORD=secret123\nthis line has no separator\nBASE_URL=http://reader.example/\n",
	)
}

func TestFaultPartialWriteConflictKeepsPreviousFile(t *testing.T) {
	forgeRenameExpectRejected(t,
		map[string]string{"LEGACY_ADMIN_USER": "ADMIN_USERNAME"},
		"LEGACY_ADMIN_USER=bob\nADMIN_PASSWORD=secret123\nADMIN_USERNAME=alice\n",
	)
}

func TestRenameConfigKeysRejectsInvalidRenames(t *testing.T) {
	input := "A=1\nB=2\n"
	for _, renames := range []map[string]string{
		{"": "X"},
		{"A": ""},
		{"A": "A"},
		{"A=B": "C"},
		{"A": "B C"},
		{"A": "#C"},
		{"A": "B", "B": "C"},
	} {
		forgeRenameExpectRejected(t, renames, input)
	}
}

func TestRenameConfigKeysPreservesPermissions(t *testing.T) {
	path := forgeRenameFixture(t, "LEGACY_ADMIN_USER=bob\n", 0o640)
	if err := RenameConfigKeys(path, map[string]string{"LEGACY_ADMIN_USER": "ADMIN_USERNAME"}); err != nil {
		t.Fatalf("RenameConfigKeys failed: %v", err)
	}
	if got := forgeRenameContent(t, path); got != "ADMIN_USERNAME=bob\n" {
		t.Fatalf("unexpected content after rename: %q", got)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o640 {
		t.Fatalf("expected permissions 0640 to be kept, got %v", info.Mode().Perm())
	}
}

func TestRenameConfigKeysMissingFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.conf")
	if err := RenameConfigKeys(path, map[string]string{"A": "B"}); err == nil {
		t.Fatal("expected an error for a missing configuration file")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("a missing configuration file must not be created, stat returned %v", err)
	}
}
