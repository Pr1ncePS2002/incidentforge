package config // import "miniflux.app/v2/internal/config"

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func forgeValidate(t *testing.T, lines ...string) error {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed before validation: %v", err)
	}
	return parser.options.Validate()
}

func TestFaultConditionalMissingAdminUsername(t *testing.T) {
	err := forgeValidate(t, "CREATE_ADMIN=1", "ADMIN_PASSWORD=secret123")
	if err == nil {
		t.Fatal("expected an error when CREATE_ADMIN is on and ADMIN_USERNAME is missing")
	}
	if !strings.Contains(err.Error(), "ADMIN_USERNAME") {
		t.Errorf("error should name ADMIN_USERNAME, got %q", err)
	}
	if strings.Contains(err.Error(), "ADMIN_PASSWORD") {
		t.Errorf("error should not blame ADMIN_PASSWORD, got %q", err)
	}
}

func TestFaultConditionalMissingAdminPassword(t *testing.T) {
	err := forgeValidate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin")
	if err == nil {
		t.Fatal("expected an error when CREATE_ADMIN is on and ADMIN_PASSWORD is missing")
	}
	if !strings.Contains(err.Error(), "ADMIN_PASSWORD") {
		t.Errorf("error should name ADMIN_PASSWORD, got %q", err)
	}
	if strings.Contains(err.Error(), "ADMIN_USERNAME") {
		t.Errorf("error should not blame ADMIN_USERNAME, got %q", err)
	}
}

func TestFaultEmptyAdminCredentials(t *testing.T) {
	err := forgeValidate(t, "CREATE_ADMIN=yes", "ADMIN_USERNAME=   ", "ADMIN_PASSWORD=secret123")
	if err == nil || !strings.Contains(err.Error(), "ADMIN_USERNAME") {
		t.Fatalf("a whitespace-only ADMIN_USERNAME must be rejected, got %v", err)
	}
}

func TestFaultSeveralBadAdminCredentials(t *testing.T) {
	err := forgeValidate(t, "CREATE_ADMIN=true")
	if err == nil {
		t.Fatal("expected an error when CREATE_ADMIN is on and no credentials are set")
	}
	for _, key := range []string{"ADMIN_USERNAME", "ADMIN_PASSWORD", "CREATE_ADMIN"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
}

func TestCreateAdminOffNeedsNoCredentials(t *testing.T) {
	if err := forgeValidate(t); err != nil {
		t.Fatalf("defaults must still validate, got %v", err)
	}
	if err := forgeValidate(t, "CREATE_ADMIN=0"); err != nil {
		t.Fatalf("CREATE_ADMIN off must not require credentials, got %v", err)
	}
}

func TestCreateAdminWithCredentialsValidates(t *testing.T) {
	if err := forgeValidate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin", "ADMIN_PASSWORD=secret123"); err != nil {
		t.Fatalf("complete admin credentials must validate, got %v", err)
	}
}

func TestCreateAdminPasswordFromFileValidates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "password")
	if err := os.WriteFile(path, []byte("secret123\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := forgeValidate(t, "CREATE_ADMIN=1", "ADMIN_USERNAME=admin", "ADMIN_PASSWORD_FILE="+path)
	if err != nil {
		t.Fatalf("a password supplied through ADMIN_PASSWORD_FILE must count, got %v", err)
	}
}
