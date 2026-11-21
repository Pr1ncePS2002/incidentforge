package systemd // import "miniflux.app/v2/internal/systemd"

import (
	"os"
	"strings"
	"testing"
	"time"
)

func forgeUnsetEnv(t *testing.T, key string) {
	t.Helper()
	t.Setenv(key, "")
	if err := os.Unsetenv(key); err != nil {
		t.Fatal(err)
	}
}

func forgeExpectKeys(t *testing.T, err error, present []string, absent []string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected an error naming %v, got nil", present)
	}
	for _, key := range present {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
	for _, key := range absent {
		if strings.Contains(err.Error(), key) {
			t.Errorf("error should not blame %s, got %q", key, err)
		}
	}
}

func TestFaultConditionalMissingNotifySocket(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "30000000")
	forgeUnsetEnv(t, "NOTIFY_SOCKET")
	_, err := LoadWatchdogSettings()
	forgeExpectKeys(t, err, []string{"NOTIFY_SOCKET"}, nil)
}

func TestFaultEmptyNotifySocket(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "30000000")
	t.Setenv("NOTIFY_SOCKET", "   ")
	_, err := LoadWatchdogSettings()
	forgeExpectKeys(t, err, []string{"NOTIFY_SOCKET"}, nil)
}

func TestFaultEmptyWatchdogInterval(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "   ")
	t.Setenv("NOTIFY_SOCKET", "/run/systemd/notify")
	_, err := LoadWatchdogSettings()
	forgeExpectKeys(t, err, []string{"WATCHDOG_USEC"}, []string{"NOTIFY_SOCKET"})
}

func TestFaultPlaceholderWatchdogInterval(t *testing.T) {
	for _, value := range []string{"changethis", "TODO", "<fill-me>"} {
		t.Run(value, func(t *testing.T) {
			t.Setenv("WATCHDOG_USEC", value)
			t.Setenv("NOTIFY_SOCKET", "/run/systemd/notify")
			_, err := LoadWatchdogSettings()
			forgeExpectKeys(t, err, []string{"WATCHDOG_USEC"}, []string{"NOTIFY_SOCKET"})
		})
	}
}

func TestFaultPlaceholderNotifySocket(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "30000000")
	t.Setenv("NOTIFY_SOCKET", "changethis")
	_, err := LoadWatchdogSettings()
	forgeExpectKeys(t, err, []string{"NOTIFY_SOCKET"}, nil)
}

func TestFaultSeveralBadWatchdogSettings(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "todo")
	forgeUnsetEnv(t, "NOTIFY_SOCKET")
	_, err := LoadWatchdogSettings()
	forgeExpectKeys(t, err, []string{"WATCHDOG_USEC", "NOTIFY_SOCKET"}, nil)
}

func TestWatchdogDisabledByDefault(t *testing.T) {
	forgeUnsetEnv(t, "WATCHDOG_USEC")
	forgeUnsetEnv(t, "NOTIFY_SOCKET")
	settings, err := LoadWatchdogSettings()
	if err != nil {
		t.Fatalf("defaults must load, got %v", err)
	}
	if settings.Enabled {
		t.Fatal("watchdog must be disabled when WATCHDOG_USEC is absent")
	}
}

func TestWatchdogEmptyIntervalMeansDisabled(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "")
	t.Setenv("NOTIFY_SOCKET", "/run/systemd/notify")
	settings, err := LoadWatchdogSettings()
	if err != nil {
		t.Fatalf("empty WATCHDOG_USEC must load, got %v", err)
	}
	if settings.Enabled {
		t.Fatal("watchdog must be disabled when WATCHDOG_USEC is empty")
	}
}

func TestWatchdogValidSettingsLoad(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", "30000000")
	t.Setenv("NOTIFY_SOCKET", "/run/systemd/notify")
	settings, err := LoadWatchdogSettings()
	if err != nil {
		t.Fatalf("valid settings must load, got %v", err)
	}
	if !settings.Enabled {
		t.Error("watchdog should be enabled")
	}
	if settings.Interval != 30*time.Second {
		t.Errorf("expected interval 30s, got %v", settings.Interval)
	}
	if settings.NotifySocket != "/run/systemd/notify" {
		t.Errorf("unexpected socket %q", settings.NotifySocket)
	}
}

func TestWatchdogAbstractSocketLoads(t *testing.T) {
	t.Setenv("WATCHDOG_USEC", " 5000000 ")
	t.Setenv("NOTIFY_SOCKET", "@/org/freedesktop/systemd1/notify")
	settings, err := LoadWatchdogSettings()
	if err != nil {
		t.Fatalf("abstract socket must load, got %v", err)
	}
	if settings.Interval != 5*time.Second {
		t.Errorf("expected interval 5s, got %v", settings.Interval)
	}
	if settings.NotifySocket != "@/org/freedesktop/systemd1/notify" {
		t.Errorf("unexpected socket %q", settings.NotifySocket)
	}
}
