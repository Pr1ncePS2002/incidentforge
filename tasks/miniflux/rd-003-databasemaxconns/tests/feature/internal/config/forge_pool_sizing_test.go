package config // import "miniflux.app/v2/internal/config"

import (
	"strings"
	"testing"
)

func forgePoolSizingFromLines(t *testing.T, lines ...string) (PoolSizing, error) {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed before sizing: %v", err)
	}
	return parser.options.DatabasePoolSizing()
}

func forgeRequireKeys(t *testing.T, err error, present []string, absent []string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected an error naming %v", present)
	}
	for _, key := range present {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
	for _, key := range absent {
		if strings.Contains(err.Error(), key) {
			t.Errorf("error should not name %s, got %q", key, err)
		}
	}
}

func TestFaultMinOverMaxConns(t *testing.T) {
	sizing, err := DerivePoolSizing(2, 30, 20)
	forgeRequireKeys(t, err, []string{"DATABASE_MIN_CONNS", "DATABASE_MAX_CONNS"}, nil)
	if sizing != (PoolSizing{}) {
		t.Errorf("expected zero sizing on error, got %+v", sizing)
	}
}

func TestFaultExceedsLimitWorkersOverMaxConns(t *testing.T) {
	_, err := DerivePoolSizing(25, 1, 20)
	forgeRequireKeys(t, err, []string{"WORKER_POOL_SIZE", "DATABASE_MAX_CONNS"}, nil)
}

func TestFaultExceedsLimitWorkersEqualMaxConns(t *testing.T) {
	_, err := DerivePoolSizing(20, 1, 20)
	forgeRequireKeys(t, err, []string{"WORKER_POOL_SIZE", "DATABASE_MAX_CONNS"}, nil)
}

func TestFaultExceedsLimitFromParsedOptions(t *testing.T) {
	_, err := forgePoolSizingFromLines(t, "DATABASE_MAX_CONNS=10", "WORKER_POOL_SIZE=16")
	forgeRequireKeys(t, err, []string{"WORKER_POOL_SIZE", "DATABASE_MAX_CONNS"}, nil)
}

func TestFaultZeroOrNegativeMaxConns(t *testing.T) {
	_, err := DerivePoolSizing(4, 0, 0)
	forgeRequireKeys(t, err, []string{"DATABASE_MAX_CONNS"}, []string{"WORKER_POOL_SIZE", "DATABASE_MIN_CONNS"})
	_, err = DerivePoolSizing(4, 0, -5)
	forgeRequireKeys(t, err, []string{"DATABASE_MAX_CONNS"}, []string{"WORKER_POOL_SIZE", "DATABASE_MIN_CONNS"})
}

func TestFaultZeroOrNegativeWorkers(t *testing.T) {
	_, err := DerivePoolSizing(0, 1, 20)
	forgeRequireKeys(t, err, []string{"WORKER_POOL_SIZE"}, []string{"DATABASE_MAX_CONNS", "DATABASE_MIN_CONNS"})
	_, err = DerivePoolSizing(-3, 1, 20)
	forgeRequireKeys(t, err, []string{"WORKER_POOL_SIZE"}, []string{"DATABASE_MAX_CONNS", "DATABASE_MIN_CONNS"})
}

func TestFaultZeroOrNegativeMinConns(t *testing.T) {
	_, err := DerivePoolSizing(4, -1, 20)
	forgeRequireKeys(t, err, []string{"DATABASE_MIN_CONNS"}, []string{"DATABASE_MAX_CONNS", "WORKER_POOL_SIZE"})
}

func TestFaultHardcodedSizeFollowsConfiguredLimits(t *testing.T) {
	sizing, err := DerivePoolSizing(30, 5, 50)
	if err != nil {
		t.Fatalf("valid limits must derive, got %v", err)
	}
	want := PoolSizing{Workers: 30, MinConns: 5, MaxConns: 50, ReservedConns: 20}
	if sizing != want {
		t.Fatalf("got %+v, want %+v", sizing, want)
	}

	sizing, err = DerivePoolSizing(3, 0, 7)
	if err != nil {
		t.Fatalf("valid limits must derive, got %v", err)
	}
	want = PoolSizing{Workers: 3, MinConns: 0, MaxConns: 7, ReservedConns: 4}
	if sizing != want {
		t.Fatalf("got %+v, want %+v", sizing, want)
	}
}

func TestFaultHardcodedSizeFromParsedOptions(t *testing.T) {
	sizing, err := forgePoolSizingFromLines(t, "DATABASE_MAX_CONNS=50", "DATABASE_MIN_CONNS=5", "WORKER_POOL_SIZE=30")
	if err != nil {
		t.Fatalf("valid configuration must derive, got %v", err)
	}
	want := PoolSizing{Workers: 30, MinConns: 5, MaxConns: 50, ReservedConns: 20}
	if sizing != want {
		t.Fatalf("got %+v, want %+v", sizing, want)
	}
}

func TestPoolSizingDefaultsStillDerive(t *testing.T) {
	sizing, err := forgePoolSizingFromLines(t)
	if err != nil {
		t.Fatalf("shipped defaults must derive, got %v", err)
	}
	if sizing.MaxConns < 1 || sizing.Workers < 1 || sizing.ReservedConns < 1 {
		t.Fatalf("unexpected default sizing %+v", sizing)
	}
	if sizing.ReservedConns != sizing.MaxConns-sizing.Workers {
		t.Fatalf("ReservedConns must equal MaxConns-Workers, got %+v", sizing)
	}
}

func TestPoolSizingBoundariesAccepted(t *testing.T) {
	if _, err := DerivePoolSizing(1, 2, 2); err != nil {
		t.Fatalf("min equal to max with one reserved connection must derive, got %v", err)
	}
	if _, err := DerivePoolSizing(19, 0, 20); err != nil {
		t.Fatalf("workers one below max must derive, got %v", err)
	}
}
