package client // import "miniflux.app/v2/internal/http/client"

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func forgeWriteOptionsFile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "client.json")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func forgeReadOptionsDoc(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("saved file is not a JSON object: %v\n%s", err, data)
	}
	return doc
}

func forgeCanonicalJSON(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func forgeAssertOnlyFile(t *testing.T, path string) {
	t.Helper()
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(path) {
		names := []string{}
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Fatalf("expected only %s in directory, found %v", filepath.Base(path), names)
	}
}

func TestFaultDroppedFieldUnknownKeys(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"30s","block_private_networks":false,"proxy_rotation":{"enabled":true,"urls":["http://proxy.example"]},"user_agent":"Miniflux"}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = 45 * time.Second
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	if got := forgeCanonicalJSON(t, doc["proxy_rotation"]); got != `{"enabled":true,"urls":["http://proxy.example"]}` {
		t.Errorf("unknown object key lost or altered: %s", got)
	}
	if got, ok := doc["user_agent"].(string); !ok || got != "Miniflux" {
		t.Errorf("unknown string key lost or altered: %#v", doc["user_agent"])
	}
	if got, ok := doc["timeout"].(string); !ok || got != "45s" {
		t.Errorf("timeout should be \"45s\", got %#v", doc["timeout"])
	}
}

func TestFaultDroppedFieldUnchangedKnownKey(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"1m30s","block_private_networks":false}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.BlockPrivateNetworks = true
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	if got, ok := doc["timeout"].(string); !ok || got != "1m30s" {
		t.Errorf("unchanged timeout must keep its original value, got %#v", doc["timeout"])
	}
	if got, ok := doc["block_private_networks"].(bool); !ok || !got {
		t.Errorf("block_private_networks should be true, got %#v", doc["block_private_networks"])
	}
}

func TestFaultDefaultOverwriteExplicitZeroKept(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"0s","block_private_networks":false,"extra":""}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = 10 * time.Second
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	v, ok := doc["block_private_networks"]
	if !ok {
		t.Fatal("explicit block_private_networks=false was dropped")
	}
	if b, isBool := v.(bool); !isBool || b {
		t.Errorf("block_private_networks should stay false, got %#v", v)
	}
	if e, ok := doc["extra"]; !ok || e != "" {
		t.Errorf("explicit empty string must be kept, got %#v (present=%v)", e, ok)
	}
}

func TestFaultDefaultOverwriteZeroTimeoutKept(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"0s","block_private_networks":true}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.BlockPrivateNetworks = false
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	if got, ok := doc["timeout"].(string); !ok || got != "0s" {
		t.Errorf("explicit zero timeout must be kept, got %#v", doc["timeout"])
	}
	v, ok := doc["block_private_networks"]
	if !ok {
		t.Fatal("setting block_private_networks to false must write false, not remove the key")
	}
	if b, isBool := v.(bool); !isBool || b {
		t.Errorf("block_private_networks should be false, got %#v", v)
	}
}

func TestFaultDefaultOverwriteAbsentStaysAbsent(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"30s"}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = time.Minute
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	if _, ok := doc["block_private_networks"]; ok {
		t.Errorf("absent block_private_networks must stay absent, got %#v", doc["block_private_networks"])
	}
	if got, ok := doc["timeout"].(string); !ok || got != "1m0s" {
		t.Errorf("timeout should be \"1m0s\", got %#v", doc["timeout"])
	}
}

func TestFaultTypeDriftDurationStaysString(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"2m","block_private_networks":false,"max_redirects":10,"tags":["a"]}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.BlockPrivateNetworks = true
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	s, ok := doc["timeout"].(string)
	if !ok {
		t.Fatalf("timeout changed type: %#v", doc["timeout"])
	}
	if d, err := time.ParseDuration(s); err != nil || d != 2*time.Minute {
		t.Errorf("timeout should still mean 2m, got %q", s)
	}
	if n, ok := doc["max_redirects"].(float64); !ok || n != 10 {
		t.Errorf("numeric unknown key changed: %#v", doc["max_redirects"])
	}
	if l, ok := doc["tags"].([]any); !ok || len(l) != 1 || l[0] != "a" {
		t.Errorf("list unknown key changed: %#v", doc["tags"])
	}
}

func TestFaultTypeDriftChangedTimeoutWrittenAsString(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"20s"}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = 45 * time.Second
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	doc := forgeReadOptionsDoc(t, path)
	s, ok := doc["timeout"].(string)
	if !ok {
		t.Fatalf("changed timeout must be written as a duration string, got %#v", doc["timeout"])
	}
	if d, err := time.ParseDuration(s); err != nil || d != 45*time.Second {
		t.Errorf("timeout should mean 45s, got %q", s)
	}
	opts, err := ReadOptionsFile(path)
	if err != nil {
		t.Fatalf("re-read failed: %v", err)
	}
	if opts.Timeout != 45*time.Second {
		t.Errorf("re-read timeout = %s, want 45s", opts.Timeout)
	}
}

func TestFaultPartialWriteMutateError(t *testing.T) {
	original := `{"timeout":"30s",  "block_private_networks": true, "x": [1,2]}`
	path := forgeWriteOptionsFile(t, original)
	sentinel := errors.New("boom")
	err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = time.Hour
		o.BlockPrivateNetworks = false
		return sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected the mutate error to be returned, got %v", err)
	}
	data, rerr := os.ReadFile(path)
	if rerr != nil {
		t.Fatal(rerr)
	}
	if string(data) != original {
		t.Errorf("failed update must leave the file untouched, got %s", data)
	}
	forgeAssertOnlyFile(t, path)
}

func TestFaultPartialWriteInvalidValue(t *testing.T) {
	original := `{"timeout":"30s","block_private_networks":true}`
	path := forgeWriteOptionsFile(t, original)
	err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = -time.Second
		return nil
	})
	if err == nil {
		t.Fatal("a negative timeout must be rejected")
	}
	data, rerr := os.ReadFile(path)
	if rerr != nil {
		t.Fatal(rerr)
	}
	if string(data) != original {
		t.Errorf("rejected update must leave the file untouched, got %s", data)
	}
	forgeAssertOnlyFile(t, path)
}

func TestOptionsUpdateWithoutChangeLeavesFileIdentical(t *testing.T) {
	original := `{"timeout":"30s",   "block_private_networks":false, "other": {"a": 1}}`
	path := forgeWriteOptionsFile(t, original)
	if err := UpdateOptionsFile(path, func(o *Options) error { return nil }); err != nil {
		t.Fatalf("no-op update failed: %v", err)
	}
	if err := UpdateOptionsFile(path, nil); err != nil {
		t.Fatalf("nil mutate update failed: %v", err)
	}
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.Timeout = 30 * time.Second
		o.BlockPrivateNetworks = false
		return nil
	}); err != nil {
		t.Fatalf("same-value update failed: %v", err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != original {
		t.Errorf("no-change update rewrote the file: %s", data)
	}
	forgeAssertOnlyFile(t, path)
}

func TestOptionsUpdateRoundTripAndNoTempFiles(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"5s","block_private_networks":false}`)
	if err := UpdateOptionsFile(path, func(o *Options) error {
		o.BlockPrivateNetworks = true
		return nil
	}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	opts, err := ReadOptionsFile(path)
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	if opts.Timeout != 5*time.Second || !opts.BlockPrivateNetworks {
		t.Errorf("unexpected options after round trip: timeout=%s block=%v", opts.Timeout, opts.BlockPrivateNetworks)
	}
	forgeAssertOnlyFile(t, path)
}

func TestReadOptionsFileDecodesValues(t *testing.T) {
	path := forgeWriteOptionsFile(t, `{"timeout":"1m30s","block_private_networks":true,"unknown":1}`)
	opts, err := ReadOptionsFile(path)
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	if opts.Timeout != 90*time.Second || !opts.BlockPrivateNetworks {
		t.Errorf("unexpected options: timeout=%s block=%v", opts.Timeout, opts.BlockPrivateNetworks)
	}

	empty := forgeWriteOptionsFile(t, `{}`)
	opts, err = ReadOptionsFile(empty)
	if err != nil {
		t.Fatalf("empty object should load: %v", err)
	}
	if opts.Timeout != 0 || opts.BlockPrivateNetworks {
		t.Errorf("empty object should give zero options")
	}
}

func TestReadOptionsFileRejectsMalformed(t *testing.T) {
	for _, content := range []string{
		`[1,2]`,
		`null`,
		`{"timeout":30}`,
		`{"timeout":"soon"}`,
		`{"timeout":"-5s"}`,
		`{"block_private_networks":"yes"}`,
		`{not json`,
	} {
		path := forgeWriteOptionsFile(t, content)
		if _, err := ReadOptionsFile(path); err == nil {
			t.Errorf("expected an error for %s", content)
		}
		if err := UpdateOptionsFile(path, func(o *Options) error {
			o.BlockPrivateNetworks = true
			return nil
		}); err == nil {
			t.Errorf("update should refuse malformed file %s", content)
		}
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if string(data) != content {
			t.Errorf("malformed file must not be rewritten, got %s", data)
		}
	}
}
