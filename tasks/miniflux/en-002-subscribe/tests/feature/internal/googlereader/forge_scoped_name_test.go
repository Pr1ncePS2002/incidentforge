package googlereader // import "miniflux.app/v2/internal/googlereader"

import (
	"os"
	"strings"
	"testing"
)

const forgeFeedURL = "https://example.org/feed.xml"

func TestFaultUnscopedKeySubscriptionName(t *testing.T) {
	prod, err := SubscriptionName(NameSettings{Environment: "production"}, 42, forgeFeedURL)
	if err != nil {
		t.Fatalf("production name failed: %v", err)
	}
	stg, err := SubscriptionName(NameSettings{Environment: "staging"}, 42, forgeFeedURL)
	if err != nil {
		t.Fatalf("staging name failed: %v", err)
	}
	if prod == stg {
		t.Fatalf("staging and production must not share a name, both got %q", prod)
	}
	if !strings.HasPrefix(prod, "production:") {
		t.Errorf("production name must be scoped, got %q", prod)
	}
	if !strings.HasPrefix(stg, "staging:") {
		t.Errorf("staging name must be scoped, got %q", stg)
	}
}

func TestFaultUnscopedKeyScopedName(t *testing.T) {
	dev, err := ScopedName(NameSettings{Environment: "development"}, "a", "b")
	if err != nil {
		t.Fatal(err)
	}
	tst, err := ScopedName(NameSettings{Environment: "test"}, "a", "b")
	if err != nil {
		t.Fatal(err)
	}
	if dev == tst {
		t.Fatalf("different environments must yield different names, got %q", dev)
	}
	if dev != "development:a:b" || tst != "test:a:b" {
		t.Errorf("unexpected names %q and %q", dev, tst)
	}
}

func TestFaultWrongEnvSourceFromSetting(t *testing.T) {
	t.Setenv("MINIFLUX_ENVIRONMENT", "staging")
	settings := NameSettingsFromEnv()
	if settings.Environment != "staging" {
		t.Fatalf("expected configured environment staging, got %q", settings.Environment)
	}
	name, err := SubscriptionName(settings, 7, forgeFeedURL)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(name, "staging:") {
		t.Fatalf("name must use the configured environment, got %q", name)
	}
}

func TestFaultUnknownEnvRejected(t *testing.T) {
	for _, env := range []string{"", "   ", "prod", "Production", "qa", "staging:extra"} {
		if _, err := ScopedName(NameSettings{Environment: env}, "x"); err == nil {
			t.Errorf("environment %q must be rejected by ScopedName", env)
		} else if !strings.Contains(err.Error(), "MINIFLUX_ENVIRONMENT") {
			t.Errorf("error for %q must name MINIFLUX_ENVIRONMENT, got %q", env, err)
		}
		if _, err := SubscriptionName(NameSettings{Environment: env}, 1, forgeFeedURL); err == nil {
			t.Errorf("environment %q must be rejected by SubscriptionName", env)
		} else if !strings.Contains(err.Error(), "MINIFLUX_ENVIRONMENT") {
			t.Errorf("error for %q must name MINIFLUX_ENVIRONMENT, got %q", env, err)
		}
	}
}

func TestFaultUnknownEnvFromEmptySetting(t *testing.T) {
	t.Setenv("MINIFLUX_ENVIRONMENT", "")
	_, err := SubscriptionName(NameSettingsFromEnv(), 1, forgeFeedURL)
	if err == nil {
		t.Fatal("an empty MINIFLUX_ENVIRONMENT must not fall back to the default")
	}
	if !strings.Contains(err.Error(), "MINIFLUX_ENVIRONMENT") {
		t.Fatalf("error must name MINIFLUX_ENVIRONMENT, got %q", err)
	}
}

func TestFaultSeparatorInjection(t *testing.T) {
	s := NameSettings{Environment: "production"}
	joined, err := ScopedName(s, "a:b")
	if err != nil {
		t.Fatal(err)
	}
	split, err := ScopedName(s, "a", "b")
	if err != nil {
		t.Fatal(err)
	}
	if joined == split {
		t.Fatalf("a part containing the separator must not collide, both got %q", joined)
	}
	sub, err := SubscriptionName(s, 1, "x:y")
	if err != nil {
		t.Fatal(err)
	}
	other, err := ScopedName(s, "googlereader", "subscription", "1", "x", "y")
	if err != nil {
		t.Fatal(err)
	}
	if sub == other {
		t.Fatalf("feed URL containing the separator collided with another name: %q", sub)
	}
	if strings.Count(sub, ":") != 4 {
		t.Errorf("subscription name must contain exactly four separators, got %q", sub)
	}
}

func TestDefaultEnvironmentNameIsStable(t *testing.T) {
	t.Setenv("MINIFLUX_ENVIRONMENT", "placeholder")
	os.Unsetenv("MINIFLUX_ENVIRONMENT")
	settings := NameSettingsFromEnv()
	if settings.Environment != "production" {
		t.Fatalf("unset MINIFLUX_ENVIRONMENT must default to production, got %q", settings.Environment)
	}
	name, err := SubscriptionName(settings, 42, forgeFeedURL)
	if err != nil {
		t.Fatal(err)
	}
	want := "production:googlereader:subscription:42:https%3A%2F%2Fexample.org%2Ffeed.xml"
	if name != want {
		t.Fatalf("default environment name changed: got %q want %q", name, want)
	}
}

func TestScopedNameNeedsAtLeastOnePart(t *testing.T) {
	if _, err := ScopedName(NameSettings{Environment: "production"}); err == nil {
		t.Fatal("a name without parts must be rejected")
	}
}
