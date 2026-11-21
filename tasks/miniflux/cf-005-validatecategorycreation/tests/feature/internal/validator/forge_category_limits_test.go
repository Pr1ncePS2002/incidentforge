package validator

import (
	"strings"
	"testing"
)

func TestFaultInvertedRangeCategoryTitleLimits(t *testing.T) {
	err := CategoryTitleLimits{MinLength: 50, MaxLength: 20}.Validate()
	if err == nil {
		t.Fatal("expected an error when MinLength is greater than MaxLength")
	}
	for _, field := range []string{"MinLength", "MaxLength"} {
		if !strings.Contains(err.Error(), field) {
			t.Errorf("error should name %s, got %q", field, err)
		}
	}
}

func TestFaultInvertedRangeRejectedByCheckTitle(t *testing.T) {
	err := CategoryTitleLimits{MinLength: 10, MaxLength: 5}.CheckTitle("abcdefg")
	if err == nil {
		t.Fatal("CheckTitle must reject inverted limits")
	}
	if !strings.Contains(err.Error(), "MinLength") || !strings.Contains(err.Error(), "MaxLength") {
		t.Errorf("error should name both MinLength and MaxLength, got %q", err)
	}
}

func TestFaultNegativeOrZeroMinLength(t *testing.T) {
	for _, min := range []int{0, -3} {
		err := CategoryTitleLimits{MinLength: min, MaxLength: 100}.Validate()
		if err == nil {
			t.Fatalf("MinLength %d must be rejected", min)
		}
		if !strings.Contains(err.Error(), "MinLength") {
			t.Errorf("error should name MinLength, got %q", err)
		}
		if strings.Contains(err.Error(), "MaxLength") {
			t.Errorf("error should not blame MaxLength, got %q", err)
		}
	}
}

func TestFaultNegativeOrZeroMaxLength(t *testing.T) {
	for _, max := range []int{0, -1} {
		err := CategoryTitleLimits{MinLength: 1, MaxLength: max}.Validate()
		if err == nil {
			t.Fatalf("MaxLength %d must be rejected", max)
		}
		if !strings.Contains(err.Error(), "MaxLength") {
			t.Errorf("error should name MaxLength, got %q", err)
		}
	}
}

func TestFaultBoundaryEqualLimitsAllowed(t *testing.T) {
	limits := CategoryTitleLimits{MinLength: 4, MaxLength: 4}
	if err := limits.Validate(); err != nil {
		t.Fatalf("MinLength == MaxLength must be allowed, got %v", err)
	}
	if err := limits.CheckTitle("news"); err != nil {
		t.Fatalf("a title of exactly the fixed length must be accepted, got %v", err)
	}
	if err := limits.CheckTitle("new"); err == nil {
		t.Fatal("a title shorter than the fixed length must be rejected")
	}
	if err := limits.CheckTitle("newsy"); err == nil {
		t.Fatal("a title longer than the fixed length must be rejected")
	}
}

func TestDefaultCategoryTitleLimitsValidate(t *testing.T) {
	if DefaultCategoryTitleLimits.MinLength != 1 || DefaultCategoryTitleLimits.MaxLength != 255 {
		t.Fatalf("unexpected defaults: %+v", DefaultCategoryTitleLimits)
	}
	if err := DefaultCategoryTitleLimits.Validate(); err != nil {
		t.Fatalf("default limits must validate, got %v", err)
	}
	if err := DefaultCategoryTitleLimits.CheckTitle("Technology"); err != nil {
		t.Fatalf("a normal title must pass default limits, got %v", err)
	}
}

func TestCategoryTitleLengthBounds(t *testing.T) {
	limits := CategoryTitleLimits{MinLength: 3, MaxLength: 5}

	if err := limits.CheckTitle("ab"); err == nil || !strings.Contains(err.Error(), "MinLength") {
		t.Errorf("too short title should be rejected naming MinLength, got %v", err)
	}
	if err := limits.CheckTitle("abcdef"); err == nil || !strings.Contains(err.Error(), "MaxLength") {
		t.Errorf("too long title should be rejected naming MaxLength, got %v", err)
	}
	for _, title := range []string{"abc", "abcd", "abcde"} {
		if err := limits.CheckTitle(title); err != nil {
			t.Errorf("title %q is within inclusive bounds, got %v", title, err)
		}
	}
}

func TestCategoryTitleLengthCountsCharacters(t *testing.T) {
	limits := CategoryTitleLimits{MinLength: 1, MaxLength: 3}
	if err := limits.CheckTitle("été"); err != nil {
		t.Fatalf("length must be counted in characters, not bytes, got %v", err)
	}
}
