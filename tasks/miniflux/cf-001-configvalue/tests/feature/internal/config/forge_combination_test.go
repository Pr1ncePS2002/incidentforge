package config // import "miniflux.app/v2/internal/config"

import (
	"strings"
	"testing"
)

func forgeComboValidate(t *testing.T, lines ...string) error {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed before validation: %v", err)
	}
	return parser.options.Validate()
}

func TestFaultInvertedRangeSchedulerInterval(t *testing.T) {
	err := forgeComboValidate(t,
		"POLLING_SCHEDULER=entry_frequency",
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=120",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60",
	)
	if err == nil {
		t.Fatal("expected an error when the minimum interval is greater than the maximum interval")
	}
	for _, key := range []string{"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL", "SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
}

func TestFaultInvertedRangeMinAboveDefaultMax(t *testing.T) {
	err := forgeComboValidate(t, "SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=100000")
	if err == nil {
		t.Fatal("expected an error when the minimum interval exceeds the default maximum interval")
	}
	if !strings.Contains(err.Error(), "SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL") || !strings.Contains(err.Error(), "SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL") {
		t.Errorf("error should name both interval settings, got %q", err)
	}
}

func TestFaultBoundaryEqualOffByOne(t *testing.T) {
	err := forgeComboValidate(t,
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=61",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60",
	)
	if err == nil {
		t.Fatal("a minimum one minute above the maximum must be rejected")
	}
}

func TestSchedulerIntervalEqualBoundaryAllowed(t *testing.T) {
	err := forgeComboValidate(t,
		"POLLING_SCHEDULER=entry_frequency",
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=60",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60",
	)
	if err != nil {
		t.Fatalf("equal minimum and maximum intervals must validate, got %v", err)
	}
}

func TestSchedulerIntervalOrderedRangeValidates(t *testing.T) {
	err := forgeComboValidate(t,
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=10",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=600",
	)
	if err != nil {
		t.Fatalf("an ordered interval range must validate, got %v", err)
	}
}

func TestFaultMutuallyExclusiveCertDomainAndFiles(t *testing.T) {
	err := forgeComboValidate(t,
		"CERT_DOMAIN=rss.example.org",
		"CERT_FILE=/etc/ssl/miniflux.crt",
		"KEY_FILE=/etc/ssl/miniflux.key",
	)
	if err == nil {
		t.Fatal("expected an error when CERT_DOMAIN is combined with certificate files")
	}
	for _, key := range []string{"CERT_DOMAIN", "CERT_FILE", "KEY_FILE"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
}

func TestFaultMutuallyExclusiveCertDomainAndCertFileOnly(t *testing.T) {
	err := forgeComboValidate(t,
		"CERT_DOMAIN=rss.example.org",
		"CERT_FILE=/etc/ssl/miniflux.crt",
	)
	if err == nil {
		t.Fatal("expected an error when CERT_DOMAIN is combined with CERT_FILE")
	}
	if !strings.Contains(err.Error(), "CERT_DOMAIN") || !strings.Contains(err.Error(), "CERT_FILE") {
		t.Errorf("error should name CERT_DOMAIN and CERT_FILE, got %q", err)
	}
	if strings.Contains(err.Error(), "KEY_FILE") {
		t.Errorf("error should not blame KEY_FILE, got %q", err)
	}
}

func TestFaultMutuallyExclusiveCertDomainAndKeyFileOnly(t *testing.T) {
	err := forgeComboValidate(t,
		"CERT_DOMAIN=rss.example.org",
		"KEY_FILE=/etc/ssl/miniflux.key",
	)
	if err == nil {
		t.Fatal("expected an error when CERT_DOMAIN is combined with KEY_FILE")
	}
	if !strings.Contains(err.Error(), "CERT_DOMAIN") || !strings.Contains(err.Error(), "KEY_FILE") {
		t.Errorf("error should name CERT_DOMAIN and KEY_FILE, got %q", err)
	}
	if strings.Contains(err.Error(), "CERT_FILE") {
		t.Errorf("error should not blame CERT_FILE, got %q", err)
	}
}

func TestTLSSingleModeStillValidates(t *testing.T) {
	if err := forgeComboValidate(t, "CERT_DOMAIN=rss.example.org"); err != nil {
		t.Fatalf("CERT_DOMAIN alone must validate, got %v", err)
	}
	if err := forgeComboValidate(t, "CERT_FILE=/etc/ssl/miniflux.crt", "KEY_FILE=/etc/ssl/miniflux.key"); err != nil {
		t.Fatalf("certificate files alone must validate, got %v", err)
	}
}

func TestShippedDefaultsStillValidate(t *testing.T) {
	if err := forgeComboValidate(t); err != nil {
		t.Fatalf("defaults must validate, got %v", err)
	}
}
