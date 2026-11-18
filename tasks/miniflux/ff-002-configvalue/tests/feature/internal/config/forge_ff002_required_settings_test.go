package config // import "miniflux.app/v2/internal/config"

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func ff002Validate(t *testing.T, lines ...string) error {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed before validation: %v", err)
	}
	return parser.options.Validate()
}

func ff002MustName(t *testing.T, err error, keys ...string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected a validation error naming %v, got nil", keys)
	}
	for _, key := range keys {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
}

func ff002MustNotName(t *testing.T, err error, keys ...string) {
	t.Helper()
	if err == nil {
		return
	}
	for _, key := range keys {
		if strings.Contains(err.Error(), key) {
			t.Errorf("error should not blame %s, got %q", key, err)
		}
	}
}

func TestFaultConditionalMissingAdminPassword(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin")
	ff002MustName(t, err, "ADMIN_PASSWORD", "CREATE_ADMIN")
	ff002MustNotName(t, err, "ADMIN_USERNAME", "DATABASE_URL")
}

func TestFaultConditionalMissingAdminUsername(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_PASSWORD=s3cret-Passw0rd")
	ff002MustName(t, err, "ADMIN_USERNAME", "CREATE_ADMIN")
	ff002MustNotName(t, err, "ADMIN_PASSWORD")
}

func TestFaultEmptyAdminUsername(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=yes", "ADMIN_USERNAME=   ", "ADMIN_PASSWORD=s3cret-Passw0rd")
	ff002MustName(t, err, "ADMIN_USERNAME")
	ff002MustNotName(t, err, "ADMIN_PASSWORD")
}

func TestFaultPlaceholderAdminPassword(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin", "ADMIN_PASSWORD=changethis")
	ff002MustName(t, err, "ADMIN_PASSWORD")
	ff002MustNotName(t, err, "ADMIN_USERNAME", "DATABASE_URL")
}

func TestFaultPlaceholderAdminPasswordUpperCase(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin", "ADMIN_PASSWORD=TODO")
	ff002MustName(t, err, "ADMIN_PASSWORD")
}

func TestFaultPlaceholderAdminUsernameAngleBrackets(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=<fill-me>", "ADMIN_PASSWORD=s3cret-Passw0rd")
	ff002MustName(t, err, "ADMIN_USERNAME")
	ff002MustNotName(t, err, "ADMIN_PASSWORD")
}

func TestFaultPlaceholderAdminPasswordFromFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "password")
	if err := os.WriteFile(path, []byte("changethis\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin", "ADMIN_PASSWORD_FILE="+path)
	ff002MustName(t, err, "ADMIN_PASSWORD")
}

func TestFaultPlaceholderDatabaseURL(t *testing.T) {
	err := ff002Validate(t, "DATABASE_URL=todo")
	ff002MustName(t, err, "DATABASE_URL")
	ff002MustNotName(t, err, "ADMIN_USERNAME", "ADMIN_PASSWORD")
}

func TestFaultSeveralBadSettings(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=true", "ADMIN_PASSWORD=changeme", "DATABASE_URL=<fill-me>")
	ff002MustName(t, err, "ADMIN_USERNAME", "ADMIN_PASSWORD", "DATABASE_URL")
}

func TestFaultSeveralBadMissingCredentials(t *testing.T) {
	err := ff002Validate(t, "CREATE_ADMIN=true")
	ff002MustName(t, err, "ADMIN_USERNAME", "ADMIN_PASSWORD", "CREATE_ADMIN")
}

func TestRequiredSettingsDefaultsStillValidate(t *testing.T) {
	if err := ff002Validate(t); err != nil {
		t.Fatalf("shipped defaults must still validate, got %v", err)
	}
}

func TestRequiredSettingsCreateAdminOffIgnoresCredentials(t *testing.T) {
	if err := ff002Validate(t, "CREATE_ADMIN=0"); err != nil {
		t.Fatalf("CREATE_ADMIN off must not require credentials, got %v", err)
	}
	if err := ff002Validate(t, "CREATE_ADMIN=0", "ADMIN_PASSWORD=changethis"); err != nil {
		t.Fatalf("CREATE_ADMIN off must not check admin credentials, got %v", err)
	}
}

func TestRequiredSettingsCompleteConfigValidates(t *testing.T) {
	err := ff002Validate(t,
		"CREATE_ADMIN=1",
		"ADMIN_USERNAME=admin",
		"ADMIN_PASSWORD=todo-list-2024",
		"DATABASE_URL=postgres://miniflux:secret@db/miniflux?sslmode=disable", // trufflehog:ignore fake test dsn, no real host
	)
	if err != nil {
		t.Fatalf("complete, real settings must validate, got %v", err)
	}
}

func TestRequiredSettingsPasswordFromFileValidates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "password")
	if err := os.WriteFile(path, []byte("s3cret-Passw0rd\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := ff002Validate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin", "ADMIN_PASSWORD_FILE="+path); err != nil {
		t.Fatalf("a password supplied through ADMIN_PASSWORD_FILE must count, got %v", err)
	}
}
