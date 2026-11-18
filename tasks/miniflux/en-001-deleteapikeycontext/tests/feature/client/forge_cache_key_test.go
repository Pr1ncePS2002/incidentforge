package client

import (
	"strings"
	"testing"
)

func TestFaultUnscopedKeyEnvironmentsDiffer(t *testing.T) {
	prod, err := APIKeyCacheKey(CacheKeySettings{Environment: "production"}, 42)
	if err != nil {
		t.Fatalf("production key: %v", err)
	}
	stg, err := APIKeyCacheKey(CacheKeySettings{Environment: "staging"}, 42)
	if err != nil {
		t.Fatalf("staging key: %v", err)
	}
	if prod == stg {
		t.Fatalf("production and staging keys collide: %q", prod)
	}
	if !strings.Contains(stg, "staging") {
		t.Errorf("staging key %q does not carry the environment", stg)
	}
}

func TestFaultWrongEnvSourceUsesConfiguredEnvironment(t *testing.T) {
	cases := map[string]string{
		"staging":     "miniflux:staging:feed:7",
		"development": "miniflux:development:feed:7",
		"test":        "miniflux:test:feed:7",
	}
	for env, want := range cases {
		got, err := BuildCacheKey(CacheKeySettings{Environment: env}, "feed", "7")
		if err != nil {
			t.Fatalf("env %s: %v", env, err)
		}
		if got != want {
			t.Errorf("env %s: got %q, want %q", env, got, want)
		}
	}
	got, err := APIKeyCacheKey(CacheKeySettings{Environment: "staging"}, 9)
	if err != nil {
		t.Fatal(err)
	}
	if got != "miniflux:staging:api-key:9" {
		t.Errorf("got %q, want miniflux:staging:api-key:9", got)
	}
}

func TestFaultUnknownEnvRejected(t *testing.T) {
	for _, env := range []string{"", "prod", "Production", " production", "qa", "prod:staging"} {
		key, err := APIKeyCacheKey(CacheKeySettings{Environment: env}, 1)
		if err == nil {
			t.Errorf("environment %q must be rejected, got key %q", env, key)
			continue
		}
		if !strings.Contains(err.Error(), "Environment") {
			t.Errorf("error for %q must name the Environment setting, got %q", env, err)
		}
		if key != "" {
			t.Errorf("no key should be built for %q, got %q", env, key)
		}
	}
	if _, err := BuildCacheKey(CacheKeySettings{}, "feed", "1"); err == nil {
		t.Error("zero-value settings must be rejected")
	}
}

func TestFaultSeparatorInjectionRejected(t *testing.T) {
	s := CacheKeySettings{Environment: "production"}
	if key, err := BuildCacheKey(s, "a:b"); err == nil {
		t.Errorf("part containing the separator must be rejected, got %q", key)
	}
	if key, err := BuildCacheKey(s, "feed", "1:2"); err == nil {
		t.Errorf("part containing the separator must be rejected, got %q", key)
	}
	if key, err := BuildCacheKey(s, "feed", ""); err == nil {
		t.Errorf("empty part must be rejected, got %q", key)
	}
	if key, err := BuildCacheKey(s); err == nil {
		t.Errorf("no parts must be rejected, got %q", key)
	}
	ok, err := BuildCacheKey(s, "a", "b")
	if err != nil || ok != "miniflux:production:a:b" {
		t.Errorf("got %q, %v", ok, err)
	}
}

func TestDefaultEnvironmentKeyStable(t *testing.T) {
	if DefaultCacheEnvironment != "production" {
		t.Fatalf("default environment changed: %q", DefaultCacheEnvironment)
	}
	got, err := APIKeyCacheKey(CacheKeySettings{Environment: DefaultCacheEnvironment}, 42)
	if err != nil {
		t.Fatal(err)
	}
	if got != "miniflux:production:api-key:42" {
		t.Errorf("got %q, want miniflux:production:api-key:42", got)
	}
}
