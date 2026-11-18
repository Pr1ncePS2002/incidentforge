package config // import "miniflux.app/v2/internal/config"

import (
	"strings"
	"sync"
	"testing"
)

func forgeLiveParse(t *testing.T, lines ...string) *configOptions {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed: %v", err)
	}
	return parser.options
}

func forgeLivePair(name string) []string {
	return []string{"ADMIN_USERNAME=" + name, "ADMIN_PASSWORD=" + name + "-password"}
}

func TestLiveOptionsServesStartupOptionsUnchanged(t *testing.T) {
	startup := forgeLiveParse(t, "ADMIN_USERNAME=startup-admin")
	live := NewLiveOptions(startup)
	if live.Current() != startup {
		t.Fatal("without a reload Current must return the startup options unchanged")
	}
	if got := live.Current().AdminUsername(); got != "startup-admin" {
		t.Fatalf("expected startup-admin, got %q", got)
	}
	if live.Current() != live.Current() {
		t.Fatal("repeated reads without a reload must return the same options")
	}
}

func TestLiveOptionsNilServesDefaults(t *testing.T) {
	defaults := NewConfigParser().options
	live := NewLiveOptions(nil)
	cur := live.Current()
	if cur == nil {
		t.Fatal("Current must not be nil when created with nil")
	}
	if cur.AdminUsername() != defaults.AdminUsername() || cur.CreateAdmin() != defaults.CreateAdmin() || cur.OAuth2Provider() != defaults.OAuth2Provider() {
		t.Fatal("nil initial options must serve the defaults")
	}
}

func TestLiveOptionsValidReloadSucceeds(t *testing.T) {
	live := NewLiveOptions(nil)
	if err := live.Reload([]string{"ADMIN_USERNAME=ok", "   ", ""}); err != nil {
		t.Fatalf("valid reload with blank lines must succeed, got %v", err)
	}
	if got := live.Current().AdminUsername(); got != "ok" {
		t.Fatalf("expected ok, got %q", got)
	}
}

func TestFaultStaleCaptureNextReadSeesReload(t *testing.T) {
	live := NewLiveOptions(forgeLiveParse(t, "ADMIN_USERNAME=before"))
	captured := live.Current()

	if err := live.Reload([]string{"ADMIN_USERNAME=after", "CREATE_ADMIN=1", "ADMIN_PASSWORD=secret123"}); err != nil {
		t.Fatalf("reload failed: %v", err)
	}
	if got := live.Current().AdminUsername(); got != "after" {
		t.Fatalf("next read after reload must return the new value, got %q", got)
	}
	if !live.Current().CreateAdmin() {
		t.Fatal("next read after reload must see CREATE_ADMIN enabled")
	}
	if got := captured.AdminUsername(); got != "before" {
		t.Fatalf("earlier snapshots must never be mutated in place, got %q", got)
	}

	if err := live.Reload([]string{"ADMIN_USERNAME=again"}); err != nil {
		t.Fatalf("second reload failed: %v", err)
	}
	if got := live.Current().AdminUsername(); got != "again" {
		t.Fatalf("second reload must also be visible on next read, got %q", got)
	}
}

func TestFaultInvalidReloadKeepsLastGoodValue(t *testing.T) {
	live := NewLiveOptions(nil)
	if err := live.Reload([]string{"ADMIN_USERNAME=good"}); err != nil {
		t.Fatalf("good reload failed: %v", err)
	}
	good := live.Current()

	err := live.Reload([]string{"ADMIN_USERNAME=bad", "OAUTH2_PROVIDER=oidc"})
	if err == nil {
		t.Fatal("reload with OIDC provider but no discovery endpoint must be rejected")
	}
	if !strings.Contains(err.Error(), "OAUTH2_OIDC_DISCOVERY_ENDPOINT") {
		t.Errorf("error must name OAUTH2_OIDC_DISCOVERY_ENDPOINT, got %q", err)
	}
	if live.Current() != good {
		t.Fatal("rejected reload must keep the last good options active")
	}
	if got := live.Current().AdminUsername(); got != "good" {
		t.Fatalf("rejected reload must not leak values, got %q", got)
	}
	if live.Current().OAuth2Provider() == "oidc" {
		t.Fatal("rejected reload must not leak OAUTH2_PROVIDER")
	}

	if err := live.Reload([]string{"ADMIN_USERNAME=fixed"}); err != nil {
		t.Fatalf("a later valid reload must succeed, got %v", err)
	}
	if got := live.Current().AdminUsername(); got != "fixed" {
		t.Fatalf("expected fixed, got %q", got)
	}
}

func TestFaultInvalidReloadMalformedLine(t *testing.T) {
	live := NewLiveOptions(forgeLiveParse(t, "ADMIN_USERNAME=good"))
	good := live.Current()

	err := live.Reload([]string{"ADMIN_USERNAME=bad", "BROKEN_LINE_WITHOUT_VALUE"})
	if err == nil {
		t.Fatal("a line without '=' must be rejected")
	}
	if !strings.Contains(err.Error(), "BROKEN_LINE_WITHOUT_VALUE") {
		t.Errorf("error must name the offending line, got %q", err)
	}
	if live.Current() != good || live.Current().AdminUsername() != "good" {
		t.Fatal("rejected reload must keep the last good options active")
	}

	if err := live.Reload([]string{"=value"}); err == nil {
		t.Fatal("a line with an empty key must be rejected")
	}
	if live.Current() != good {
		t.Fatal("rejected reload must keep the last good options active")
	}
}

func TestFaultPartialReloadPairsSwapTogether(t *testing.T) {
	live := NewLiveOptions(forgeLiveParse(t, forgeLivePair("alpha")...))

	done := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-done:
					return
				default:
				}
				opts := live.Current()
				user, pass := opts.AdminUsername(), opts.AdminPassword()
				if pass != user+"-password" {
					t.Errorf("observed mixed snapshot: user=%q password=%q", user, pass)
					return
				}
			}
		}()
	}

	var reloadErr error
	for i := 0; i < 200; i++ {
		name := "alpha"
		if i%2 == 1 {
			name = "beta"
		}
		if err := live.Reload(forgeLivePair(name)); err != nil {
			reloadErr = err
			break
		}
	}
	close(done)
	wg.Wait()

	if reloadErr != nil {
		t.Fatalf("reload failed: %v", reloadErr)
	}
	if got := live.Current().AdminUsername(); got != "beta" {
		t.Fatalf("expected final username beta, got %q", got)
	}
	if got := live.Current().AdminPassword(); got != "beta-password" {
		t.Fatalf("expected final password beta-password, got %q", got)
	}
}

func TestFaultReloadUnsetFallsBackToDefault(t *testing.T) {
	defaults := NewConfigParser().options
	live := NewLiveOptions(forgeLiveParse(t, "ADMIN_USERNAME=custom-admin", "CREATE_ADMIN=1", "ADMIN_PASSWORD=secret123"))

	if err := live.Reload([]string{"ADMIN_PASSWORD=secret123"}); err != nil {
		t.Fatalf("reload failed: %v", err)
	}
	if got := live.Current().AdminUsername(); got != defaults.AdminUsername() {
		t.Fatalf("removed ADMIN_USERNAME must fall back to default %q, got %q", defaults.AdminUsername(), got)
	}
	if live.Current().CreateAdmin() != defaults.CreateAdmin() {
		t.Fatal("removed CREATE_ADMIN must fall back to its default")
	}
	if got := live.Current().AdminPassword(); got != "secret123" {
		t.Fatalf("kept ADMIN_PASSWORD must stay, got %q", got)
	}

	if err := live.Reload(nil); err != nil {
		t.Fatalf("empty reload failed: %v", err)
	}
	if got := live.Current().AdminPassword(); got != defaults.AdminPassword() {
		t.Fatalf("removed ADMIN_PASSWORD must fall back to default, got %q", got)
	}
}
