package validator // import "miniflux.app/v2/internal/validator"

import (
	"strings"
	"testing"

	"miniflux.app/v2/internal/model"
)

func forgeFeedRequest(blocklist, keeplist string) *model.FeedCreationRequest {
	return &model.FeedCreationRequest{
		FeedURL:        "https://feeds.example/rss.xml",
		CategoryID:     1,
		BlocklistRules: blocklist,
		KeeplistRules:  keeplist,
	}
}

func forgeAssertNamesBoth(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		t.Fatal("expected an error for identical blocklist and keeplist rules")
	}
	for _, field := range []string{"blocklist_rules", "keeplist_rules"} {
		if !strings.Contains(err.Error(), field) {
			t.Errorf("error should name %s, got %q", field, err)
		}
	}
}

func TestFaultMutuallyExclusiveIdenticalRules(t *testing.T) {
	err := ValidateFeedRuleCombination(forgeFeedRequest("(?i)sponsored", "(?i)sponsored"))
	forgeAssertNamesBoth(t, err)
}

func TestFaultMutuallyExclusiveSimpleWord(t *testing.T) {
	err := ValidateFeedRuleCombination(forgeFeedRequest("golang", "golang"))
	forgeAssertNamesBoth(t, err)
}

func TestFaultBoundaryEqualAfterTrimming(t *testing.T) {
	err := ValidateFeedRuleCombination(forgeFeedRequest("  breaking news\t", "breaking news\n"))
	forgeAssertNamesBoth(t, err)
}

func TestDefaultEmptyRulesValidate(t *testing.T) {
	if err := ValidateFeedRuleCombination(forgeFeedRequest("", "")); err != nil {
		t.Fatalf("empty rules must validate, got %v", err)
	}
	if err := ValidateFeedRuleCombination(forgeFeedRequest("   ", "\t")); err != nil {
		t.Fatalf("whitespace-only rules count as empty, got %v", err)
	}
	if err := ValidateFeedRuleCombination(nil); err != nil {
		t.Fatalf("nil request must return nil, got %v", err)
	}
}

func TestSingleRuleValidates(t *testing.T) {
	if err := ValidateFeedRuleCombination(forgeFeedRequest("sponsored", "")); err != nil {
		t.Fatalf("blocklist alone must validate, got %v", err)
	}
	if err := ValidateFeedRuleCombination(forgeFeedRequest("", "golang")); err != nil {
		t.Fatalf("keeplist alone must validate, got %v", err)
	}
}

func TestDifferentRulesValidate(t *testing.T) {
	if err := ValidateFeedRuleCombination(forgeFeedRequest("sponsored", "golang")); err != nil {
		t.Fatalf("different rules must validate, got %v", err)
	}
	if err := ValidateFeedRuleCombination(forgeFeedRequest("Golang", "golang")); err != nil {
		t.Fatalf("rules differing only by case must validate, got %v", err)
	}
}
