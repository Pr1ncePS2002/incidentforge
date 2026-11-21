package date // import "miniflux.app/v2/internal/reader/date"

import (
	"strings"
	"testing"
	"time"
)

func forgeExpectBothFields(t *testing.T, w OffsetWindow) {
	t.Helper()
	err := w.Validate()
	if err == nil {
		t.Fatalf("expected window %+v to be rejected", w)
	}
	for _, name := range []string{"MinOffsetSeconds", "MaxOffsetSeconds"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error for %+v should name %s, got %q", w, name, err)
		}
	}
}

func forgeTimeAt(offset int) time.Time {
	return time.Date(2024, 1, 2, 3, 4, 5, 0, time.FixedZone("forge", offset))
}

func TestFaultInvertedRangeOffsetWindow(t *testing.T) {
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: 3600, MaxOffsetSeconds: -3600})
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: 14 * 3600, MaxOffsetSeconds: -12 * 3600})
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: 1, MaxOffsetSeconds: 0})
}

func TestFaultDependentBoundWindowExcludesUTC(t *testing.T) {
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: 3600, MaxOffsetSeconds: 7200})
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: -7200, MaxOffsetSeconds: -3600})
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: 1, MaxOffsetSeconds: 14 * 3600})
}

func TestFaultBoundaryEqualOffsetWindow(t *testing.T) {
	if err := (OffsetWindow{MinOffsetSeconds: 0, MaxOffsetSeconds: 0}).Validate(); err != nil {
		t.Fatalf("equal bounds containing UTC must be allowed, got %v", err)
	}
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: 3600, MaxOffsetSeconds: 3600})
	forgeExpectBothFields(t, OffsetWindow{MinOffsetSeconds: -3600, MaxOffsetSeconds: -3600})
}

func TestDefaultOffsetWindowValidates(t *testing.T) {
	w := DefaultOffsetWindow()
	if w.MinOffsetSeconds != -12*60*60 || w.MaxOffsetSeconds != 14*60*60 {
		t.Fatalf("unexpected default window %+v", w)
	}
	if err := w.Validate(); err != nil {
		t.Fatalf("default window must validate, got %v", err)
	}
	if err := (OffsetWindow{MinOffsetSeconds: -3600, MaxOffsetSeconds: 0}).Validate(); err != nil {
		t.Fatalf("window ending at UTC must validate, got %v", err)
	}
	if err := (OffsetWindow{MinOffsetSeconds: 0, MaxOffsetSeconds: 3600}).Validate(); err != nil {
		t.Fatalf("window starting at UTC must validate, got %v", err)
	}
}

func TestDefaultOffsetWindowMatchesParser(t *testing.T) {
	w := DefaultOffsetWindow()
	for _, offset := range []int{-13 * 3600, -12 * 3600, -5 * 3600, 0, 19800, 14 * 3600, 14*3600 + 60, 15 * 3600} {
		in := forgeTimeAt(offset)
		got := w.Apply(in)
		want := checkTimezoneRange(in)
		_, gotOffset := got.Zone()
		_, wantOffset := want.Zone()
		if !got.Equal(want) || gotOffset != wantOffset {
			t.Errorf("offset %d: Apply gave %v, checkTimezoneRange gave %v", offset, got, want)
		}
	}
}

func TestOffsetWindowApplyInclusiveBounds(t *testing.T) {
	w := OffsetWindow{MinOffsetSeconds: 0, MaxOffsetSeconds: 0}
	utc := forgeTimeAt(0)
	if _, off := w.Apply(utc).Zone(); off != 0 {
		t.Fatalf("expected offset 0, got %d", off)
	}
	shifted := forgeTimeAt(3600)
	out := w.Apply(shifted)
	if _, off := out.Zone(); off != 0 || !out.Equal(shifted) {
		t.Fatalf("expected instant converted to UTC, got %v", out)
	}
	w2 := OffsetWindow{MinOffsetSeconds: -3600, MaxOffsetSeconds: 3600}
	for _, offset := range []int{-3600, 3600} {
		if _, off := w2.Apply(forgeTimeAt(offset)).Zone(); off != offset {
			t.Errorf("bound offset %d must be kept, got %d", offset, off)
		}
	}
}
