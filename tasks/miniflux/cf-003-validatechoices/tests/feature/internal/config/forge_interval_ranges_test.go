package config // import "miniflux.app/v2/internal/config"

import (
	"strings"
	"testing"
)

func forgeValidateIntervals(t *testing.T, lines ...string) error {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		t.Fatalf("parsing failed before validation: %v", err)
	}
	return parser.options.ValidateIntervalRanges()
}

func TestFaultInvertedRangeEntryFrequency(t *testing.T) {
	err := forgeValidateIntervals(t,
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=120",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60",
	)
	if err == nil {
		t.Fatal("expected an error when the entry frequency minimum is above its maximum")
	}
	for _, key := range []string{"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL", "SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
	if strings.Contains(err.Error(), "ROUND_ROBIN") {
		t.Errorf("error should not blame the round robin settings, got %q", err)
	}
}

func TestFaultInvertedRangeRoundRobin(t *testing.T) {
	err := forgeValidateIntervals(t,
		"SCHEDULER_ROUND_ROBIN_MIN_INTERVAL=600",
		"SCHEDULER_ROUND_ROBIN_MAX_INTERVAL=120",
	)
	if err == nil {
		t.Fatal("expected an error when the round robin minimum is above its maximum")
	}
	for _, key := range []string{"SCHEDULER_ROUND_ROBIN_MIN_INTERVAL", "SCHEDULER_ROUND_ROBIN_MAX_INTERVAL"} {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("error should name %s, got %q", key, err)
		}
	}
	if strings.Contains(err.Error(), "ENTRY_FREQUENCY") {
		t.Errorf("error should not blame the entry frequency settings, got %q", err)
	}
}

func TestFaultBoundaryEqualAccepted(t *testing.T) {
	if err := forgeValidateIntervals(t,
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=60",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60",
	); err != nil {
		t.Fatalf("equal entry frequency bounds must be accepted, got %v", err)
	}
	if err := forgeValidateIntervals(t,
		"SCHEDULER_ROUND_ROBIN_MIN_INTERVAL=120",
		"SCHEDULER_ROUND_ROBIN_MAX_INTERVAL=120",
	); err != nil {
		t.Fatalf("equal round robin bounds must be accepted, got %v", err)
	}
	err := forgeValidateIntervals(t,
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=61",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60",
	)
	if err == nil {
		t.Fatal("a minimum one above the maximum must be rejected")
	}
}

func TestIntervalDefaultsStillValidate(t *testing.T) {
	if err := forgeValidateIntervals(t); err != nil {
		t.Fatalf("defaults must still validate, got %v", err)
	}
}

func TestIntervalOrderedRangesValidate(t *testing.T) {
	err := forgeValidateIntervals(t,
		"SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=10",
		"SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=600",
		"SCHEDULER_ROUND_ROBIN_MIN_INTERVAL=30",
		"SCHEDULER_ROUND_ROBIN_MAX_INTERVAL=720",
	)
	if err != nil {
		t.Fatalf("ordered ranges must validate, got %v", err)
	}
}
