package config // import "miniflux.app/v2/internal/config"

import (
	"strings"
	"testing"
)

func forgeTLSValidate(t *testing.T, lines ...string) error {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed before validation: %v", err)
	}
	return parser.options.Validate()
}

func TestFaultConditionalMissingKeyFile(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=/etc/ssl/miniflux/cert.pem")
	if err == nil {
		t.Fatal("expected an error when CERT_FILE is set without KEY_FILE")
	}
	if !strings.Contains(err.Error(), "KEY_FILE") {
		t.Errorf("error should name KEY_FILE, got %q", err)
	}
	if strings.Contains(err.Error(), "CERT_FILE") {
		t.Errorf("error should not blame CERT_FILE, got %q", err)
	}
}

func TestFaultConditionalMissingCertFile(t *testing.T) {
	err := forgeTLSValidate(t, "KEY_FILE=/etc/ssl/miniflux/key.pem")
	if err == nil {
		t.Fatal("expected an error when KEY_FILE is set without CERT_FILE")
	}
	if !strings.Contains(err.Error(), "CERT_FILE") {
		t.Errorf("error should name CERT_FILE, got %q", err)
	}
	if strings.Contains(err.Error(), "KEY_FILE") {
		t.Errorf("error should not blame KEY_FILE, got %q", err)
	}
}

func TestFaultEmptyKeyFile(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=/etc/ssl/miniflux/cert.pem", "KEY_FILE=   ")
	if err == nil {
		t.Fatal("a whitespace-only KEY_FILE must be rejected when CERT_FILE is set")
	}
	if !strings.Contains(err.Error(), "KEY_FILE") {
		t.Errorf("error should name KEY_FILE, got %q", err)
	}
}

func TestFaultPlaceholderCertFile(t *testing.T) {
	for _, placeholder := range []string{"changethis", "TODO", "<fill-me>", "  ChangeMe  "} {
		t.Run(placeholder, func(t *testing.T) {
			err := forgeTLSValidate(t, "CERT_FILE="+placeholder, "KEY_FILE=/etc/ssl/miniflux/key.pem")
			if err == nil {
				t.Fatalf("placeholder CERT_FILE %q must be rejected", placeholder)
			}
			if !strings.Contains(err.Error(), "CERT_FILE") {
				t.Errorf("error should name CERT_FILE, got %q", err)
			}
			if strings.Contains(err.Error(), "KEY_FILE") {
				t.Errorf("error should not blame KEY_FILE, got %q", err)
			}
		})
	}
}

func TestFaultPlaceholderKeyFile(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=/etc/ssl/miniflux/cert.pem", "KEY_FILE=xxx")
	if err == nil || !strings.Contains(err.Error(), "KEY_FILE") {
		t.Fatalf("placeholder KEY_FILE must be rejected and named, got %v", err)
	}
}

func TestFaultSeveralBadTLSFiles(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=<fill-me>", "KEY_FILE=todo")
	if err == nil {
		t.Fatal("expected an error when both TLS settings are placeholders")
	}
	for _, key := range []string{"CERT_FILE", "KEY_FILE"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
}

func TestFaultSeveralBadPlaceholderAndMissing(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=changethis")
	if err == nil {
		t.Fatal("expected an error for a placeholder CERT_FILE and a missing KEY_FILE")
	}
	for _, key := range []string{"CERT_FILE", "KEY_FILE"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
}

func TestTLSDefaultsStillValidate(t *testing.T) {
	if err := forgeTLSValidate(t); err != nil {
		t.Fatalf("shipped defaults must still validate, got %v", err)
	}
}

func TestTLSCompletePairValidates(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=/etc/ssl/miniflux/cert.pem", "KEY_FILE=/etc/ssl/miniflux/key.pem")
	if err != nil {
		t.Fatalf("a complete TLS pair must validate, got %v", err)
	}
}

func TestTLSPathContainingPlaceholderWordValidates(t *testing.T) {
	err := forgeTLSValidate(t, "CERT_FILE=/etc/todo/cert.pem", "KEY_FILE=/srv/changeme/key.pem")
	if err != nil {
		t.Fatalf("real paths containing placeholder words must validate, got %v", err)
	}
}

func TestTLSCheckKeepsExistingOIDCValidation(t *testing.T) {
	err := forgeTLSValidate(t, "OAUTH2_PROVIDER=oidc")
	if err == nil || !strings.Contains(err.Error(), "OAUTH2_OIDC_DISCOVERY_ENDPOINT") {
		t.Fatalf("existing OIDC validation must still apply, got %v", err)
	}
}
