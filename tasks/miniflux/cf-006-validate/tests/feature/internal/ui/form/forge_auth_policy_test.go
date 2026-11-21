package form // import "miniflux.app/v2/internal/ui/form"

import (
	"strings"
	"testing"
)

func forgeAssertNames(t *testing.T, err error, want []string, notWant []string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected an error naming %v, got nil", want)
	}
	for _, name := range want {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error should name %s, got %q", name, err)
		}
	}
	for _, name := range notWant {
		if strings.Contains(err.Error(), name) {
			t.Errorf("error should not name %s, got %q", name, err)
		}
	}
}

func TestFaultInvertedRangeUsername(t *testing.T) {
	p := DefaultAuthPolicy()
	p.MinUsernameLength = 10
	p.MaxUsernameLength = 5
	forgeAssertNames(t, p.Validate(),
		[]string{"MinUsernameLength", "MaxUsernameLength"},
		[]string{"MinPasswordLength", "MaxPasswordLength"})
}

func TestFaultInvertedRangePassword(t *testing.T) {
	p := DefaultAuthPolicy()
	p.MinPasswordLength = 64
	p.MaxPasswordLength = 8
	forgeAssertNames(t, p.Validate(),
		[]string{"MinPasswordLength", "MaxPasswordLength"},
		[]string{"MinUsernameLength", "MaxUsernameLength"})
}

func TestFaultInvertedRangeRejectedForAnyForm(t *testing.T) {
	p := DefaultAuthPolicy()
	p.MinPasswordLength = 9
	p.MaxPasswordLength = 8
	f := authForm{Username: "admin", Password: "abcdefgh"}
	forgeAssertNames(t, f.ValidateWithPolicy(p),
		[]string{"MinPasswordLength", "MaxPasswordLength"}, nil)
}

func TestFaultNegativeOrZeroLimits(t *testing.T) {
	fields := []string{"MinUsernameLength", "MaxUsernameLength", "MinPasswordLength", "MaxPasswordLength"}
	for _, field := range fields {
		for _, value := range []int{0, -1} {
			p := DefaultAuthPolicy()
			switch field {
			case "MinUsernameLength":
				p.MinUsernameLength = value
			case "MaxUsernameLength":
				p.MaxUsernameLength = value
			case "MinPasswordLength":
				p.MinPasswordLength = value
			case "MaxPasswordLength":
				p.MaxPasswordLength = value
			}
			err := p.Validate()
			if err == nil {
				t.Errorf("%s=%d must be rejected", field, value)
				continue
			}
			if !strings.Contains(err.Error(), field) {
				t.Errorf("error for %s=%d should name the field, got %q", field, value, err)
			}
			f := authForm{Username: "admin", Password: "secret123"}
			if f.ValidateWithPolicy(p) == nil {
				t.Errorf("form must be rejected under policy with %s=%d", field, value)
			}
		}
	}
}

func TestFaultBoundaryEqualAllowed(t *testing.T) {
	p := AuthPolicy{MinUsernameLength: 4, MaxUsernameLength: 4, MinPasswordLength: 8, MaxPasswordLength: 8}
	if err := p.Validate(); err != nil {
		t.Fatalf("equal min and max must be allowed, got %v", err)
	}
	if err := (authForm{Username: "üser", Password: "abcdefgh"}).ValidateWithPolicy(p); err != nil {
		t.Fatalf("credentials of exactly the allowed length (in characters) must validate, got %v", err)
	}
	if (authForm{Username: "usr", Password: "abcdefgh"}).ValidateWithPolicy(p) == nil {
		t.Error("username shorter than the exact length must be rejected")
	}
	if (authForm{Username: "users", Password: "abcdefgh"}).ValidateWithPolicy(p) == nil {
		t.Error("username longer than the exact length must be rejected")
	}
	if (authForm{Username: "user", Password: "abcdefghi"}).ValidateWithPolicy(p) == nil {
		t.Error("password longer than the exact length must be rejected")
	}
}

func TestDefaultAuthPolicyValidates(t *testing.T) {
	p := DefaultAuthPolicy()
	if p.MinUsernameLength != 1 || p.MaxUsernameLength != 255 || p.MinPasswordLength != 1 || p.MaxPasswordLength != 1024 {
		t.Fatalf("unexpected defaults: %+v", p)
	}
	if err := p.Validate(); err != nil {
		t.Fatalf("defaults must validate, got %v", err)
	}
	if err := (authForm{Username: "admin", Password: "secret123"}).ValidateWithPolicy(p); err != nil {
		t.Fatalf("normal credentials must validate under defaults, got %v", err)
	}
}

func TestPolicyRejectsEmptyAndOutOfRangeCredentials(t *testing.T) {
	p := AuthPolicy{MinUsernameLength: 3, MaxUsernameLength: 10, MinPasswordLength: 6, MaxPasswordLength: 12}
	cases := []authForm{
		{Username: "", Password: "secret123"},
		{Username: "admin", Password: ""},
		{Username: "ab", Password: "secret123"},
		{Username: "averyverylongname", Password: "secret123"},
		{Username: "admin", Password: "short"},
		{Username: "admin", Password: "waytoolongpassword"},
	}
	for _, f := range cases {
		if f.ValidateWithPolicy(p) == nil {
			t.Errorf("form %+v should be rejected", f)
		}
	}
	if err := (authForm{Username: "abc", Password: "abcdefghijkl"}).ValidateWithPolicy(p); err != nil {
		t.Errorf("inclusive bounds must validate, got %v", err)
	}
}

func TestPlainValidateUnchanged(t *testing.T) {
	if (authForm{}).Validate() == nil {
		t.Error("empty form must still be rejected")
	}
	if err := (authForm{Username: "admin", Password: "x"}).Validate(); err != nil {
		t.Errorf("filled form must still validate, got %v", err)
	}
}
