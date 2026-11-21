package validator // import "miniflux.app/v2/internal/validator"

import (
	"strings"
	"testing"
)

func forgeExpectNames(t *testing.T, err error, names ...string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected a validation error naming %v, got nil", names)
	}
	for _, name := range names {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error should name %q, got %q", name, err)
		}
	}
}

func TestFaultInvertedRangePublished(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{PublishedAfter: 2000, PublishedBefore: 1000})
	forgeExpectNames(t, err, "published_after", "published_before")
}

func TestFaultInvertedRangeChanged(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{ChangedAfter: 1700000000, ChangedBefore: 1600000000})
	forgeExpectNames(t, err, "changed_after", "changed_before")
}

func TestFaultInvertedRangeEntryID(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{AfterEntryID: 50, BeforeEntryID: 10})
	forgeExpectNames(t, err, "after_entry_id", "before_entry_id")
}

func TestFaultInvertedRangeLegacyAfterBefore(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{After: 2000, Before: 1000})
	forgeExpectNames(t, err, "after", "before")
	if err != nil && strings.Contains(err.Error(), "published_") {
		t.Errorf("error for the after/before pair must not blame published_* parameters, got %q", err)
	}
}

func TestFaultBoundaryEqualPublished(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{PublishedAfter: 1500, PublishedBefore: 1500})
	forgeExpectNames(t, err, "published_after", "published_before")
}

func TestFaultBoundaryEqualEntryID(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{AfterEntryID: 42, BeforeEntryID: 42})
	forgeExpectNames(t, err, "after_entry_id", "before_entry_id")
}

func TestFaultNegativeOrZeroEntryID(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{AfterEntryID: -1})
	forgeExpectNames(t, err, "after_entry_id")
}

func TestFaultNegativeOrZeroTimestamp(t *testing.T) {
	err := ValidateEntryQueryWindow(EntryQueryWindow{ChangedBefore: -5})
	forgeExpectNames(t, err, "changed_before")
}

func TestEntryQueryWindowDefaultsValidate(t *testing.T) {
	if err := ValidateEntryQueryWindow(EntryQueryWindow{}); err != nil {
		t.Fatalf("an empty window must validate, got %v", err)
	}
}

func TestEntryQueryWindowValidRanges(t *testing.T) {
	cases := []EntryQueryWindow{
		{After: 1000, Before: 2000},
		{PublishedAfter: 1000, PublishedBefore: 2000},
		{ChangedAfter: 1600000000, ChangedBefore: 1700000000},
		{AfterEntryID: 10, BeforeEntryID: 11},
		{PublishedAfter: 5000},
		{BeforeEntryID: 3},
		{After: 9000, PublishedBefore: 100},
		{After: 1, Before: 2, PublishedAfter: 3, PublishedBefore: 4, ChangedAfter: 5, ChangedBefore: 6, AfterEntryID: 7, BeforeEntryID: 8},
	}
	for _, c := range cases {
		if err := ValidateEntryQueryWindow(c); err != nil {
			t.Errorf("window %+v must validate, got %v", c, err)
		}
	}
}

func TestValidateDirectionUnchanged(t *testing.T) {
	if err := ValidateDirection("asc"); err != nil {
		t.Fatalf("asc must remain valid, got %v", err)
	}
	if err := ValidateDirection("sideways"); err == nil {
		t.Fatal("invalid direction must still be rejected")
	}
}
