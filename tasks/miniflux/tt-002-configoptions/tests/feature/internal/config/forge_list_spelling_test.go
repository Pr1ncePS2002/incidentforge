package config // import "miniflux.app/v2/internal/config"

import (
	"sort"
	"strings"
	"testing"
)

// forgeListKey returns a list-valued setting that has no extra value validator,
// so that only the list spelling itself is exercised.
func forgeListKey(t *testing.T) string {
	t.Helper()
	opts := NewConfigOptions()
	var keys []string
	for key, option := range opts.options {
		if option != nil && option.valueType == stringListType && option.validator == nil {
			keys = append(keys, key)
		}
	}
	if len(keys) == 0 {
		t.Fatal("no list setting without a validator found")
	}
	sort.Strings(keys)
	return keys[0]
}

func forgeListParse(t *testing.T, lines ...string) (*configParser, error) {
	t.Helper()
	parser := NewConfigParser()
	if err := parser.parseLines(lines); err != nil {
		return parser, err
	}
	return parser, parser.options.Validate()
}

func forgeListLoad(t *testing.T, key, value string) []string {
	t.Helper()
	parser, err := forgeListParse(t, key+"="+value)
	if err != nil {
		t.Fatalf("%s=%s must be accepted, got error: %v", key, value, err)
	}
	return parser.options.options[key].parsedStringList
}

func forgeListEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

var forgeListWant = []string{"10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"}

func TestCsvListStillParses(t *testing.T) {
	key := forgeListKey(t)
	got := forgeListLoad(t, key, "10.0.0.0/8, 192.168.0.0/16,172.16.0.0/12")
	if !forgeListEqual(got, forgeListWant) {
		t.Fatalf("comma-separated %s: got %q, want %q", key, got, forgeListWant)
	}
}

func TestFaultJsonListMatchesCsv(t *testing.T) {
	key := forgeListKey(t)
	csv := forgeListLoad(t, key, "10.0.0.0/8, 192.168.0.0/16,172.16.0.0/12")
	json := forgeListLoad(t, key, `["10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"]`)
	if !forgeListEqual(json, csv) {
		t.Fatalf("JSON spelling of %s gave %q, comma-separated gave %q", key, json, csv)
	}
	if !forgeListEqual(json, forgeListWant) {
		t.Fatalf("JSON spelling of %s: got %q, want %q", key, json, forgeListWant)
	}
}

func TestFaultJsonListCompactAndPadded(t *testing.T) {
	key := forgeListKey(t)
	got := forgeListLoad(t, key, `["10.0.0.0/8","192.168.0.0/16"]`)
	want := []string{"10.0.0.0/8", "192.168.0.0/16"}
	if !forgeListEqual(got, want) {
		t.Fatalf("compact JSON: got %q, want %q", got, want)
	}
	got = forgeListLoad(t, key, `[ " 10.0.0.0/8 " , "", "192.168.0.0/16" ]`)
	if !forgeListEqual(got, want) {
		t.Fatalf("padded JSON: got %q, want %q", got, want)
	}
}

func TestFaultJsonListEmptyArray(t *testing.T) {
	key := forgeListKey(t)
	got := forgeListLoad(t, key, "[]")
	if len(got) != 0 {
		t.Fatalf("%s=[] must give an empty list, got %q", key, got)
	}
}

func TestFaultGarbageUnterminatedJsonList(t *testing.T) {
	key := forgeListKey(t)
	bad := `["10.0.0.0/8",`
	_, err := forgeListParse(t, key+"="+bad)
	if err == nil {
		t.Fatalf("malformed list %s=%s must be rejected", key, bad)
	}
	if !strings.Contains(err.Error(), key) {
		t.Errorf("error should name %s, got %q", key, err)
	}
	if !strings.Contains(err.Error(), bad) {
		t.Errorf("error should contain the offending value %s, got %q", bad, err)
	}
}

func TestFaultGarbageNonStringJsonList(t *testing.T) {
	key := forgeListKey(t)
	bad := "[1, 2]"
	_, err := forgeListParse(t, key+"="+bad)
	if err == nil {
		t.Fatalf("non-string list %s=%s must be rejected", key, bad)
	}
	if !strings.Contains(err.Error(), key) || !strings.Contains(err.Error(), bad) {
		t.Errorf("error should name %s and %s, got %q", key, bad, err)
	}
}

func TestDefaultListConfigStillValidates(t *testing.T) {
	if _, err := forgeListParse(t); err != nil {
		t.Fatalf("defaults must still validate, got %v", err)
	}
}
