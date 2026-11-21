"""go surface scanner on a small synthetic repo."""

from pathlib import Path

import pytest

from incidentforge.models import Language
from incidentforge.surfaces import find_surfaces
from incidentforge.surfaces.go import MAX_EXCERPT_LINES, find_go_surfaces

CONFIG_GO = """package config

import (
\t"fmt"
\t"os"
)

// braces in strings and comments must not confuse the scanner: { } `{`
type Config struct {
\tPort       int    `env:"PORT"`
\tPoolSize   int    `env:"POOL_SIZE"`
\tNamespace  string `env:"NAMESPACE"`
}

type plain struct {
\tName string
}

func Load() (*Config, error) {
\tport := os.Getenv("PORT")
\tif port == "{" {
\t\treturn nil, fmt.Errorf("bad port %q", port)
\t}
\treturn &Config{}, nil
}

func (c *Config) Validate() error {
\tif c.PoolSize < 1 {
\t\treturn fmt.Errorf("pool size must be positive")
\t}
\treturn nil
}

func (c *Config) SaveConfig(path string) error { return nil }

func (c *Config) WorkerPoolSize() int { return c.PoolSize }

func cacheKey(id string) string {
\treturn fmt.Sprintf("cache:%s", id)
}

func topicName(ns string) string {
\treturn fmt.Sprintf("events-%s-topic", ns)
}

func Any() interface{} {
\treturn nil
}

func external(x int) int
"""

CONSUMER_GO = """package queue

type Message struct{ Body []byte }

func HandleMessage(m Message) error {
\treturn nil
}

func parseTranslationMessages() {}

func NewAPIKeyForm() {}
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "internal/config").mkdir(parents=True)
    (tmp_path / "internal/config/config.go").write_text(CONFIG_GO)
    (tmp_path / "internal/config/config_test.go").write_text("package config\nfunc TestX() {}\n")
    (tmp_path / "internal/queue").mkdir()
    (tmp_path / "internal/queue/queue.go").write_text(CONSUMER_GO)
    (tmp_path / "vendor/x").mkdir(parents=True)
    (tmp_path / "vendor/x/x.go").write_text("package x\ntype XConfig struct{}\n")
    return tmp_path


def _index(repo: Path) -> dict[tuple[str, str], str]:
    return {(s.symbol, s.kind): s.file for s in find_go_surfaces(repo)}


def test_classifies_each_kind(repo: Path) -> None:
    idx = _index(repo)
    assert idx[("Config", "settings-class")] == "internal/config/config.go"
    assert ("Config", "pool-config") in idx
    assert ("Load", "env-read") in idx
    assert ("Config.Validate", "validator") in idx
    assert ("Config.SaveConfig", "config-writer") in idx
    assert ("Config.WorkerPoolSize", "pool-config") in idx
    assert ("cacheKey", "cache-key") in idx
    assert ("topicName", "cache-key") in idx
    assert idx[("HandleMessage", "consumer")] == "internal/queue/queue.go"


def test_skips_tests_vendor_and_false_positives(repo: Path) -> None:
    symbols = {s for s, _ in _index(repo)}
    assert "TestX" not in symbols
    assert "XConfig" not in symbols
    assert "plain" not in symbols
    assert "parseTranslationMessages" not in symbols
    assert "NewAPIKeyForm" not in symbols
    assert "external" not in symbols


def test_body_extraction_ignores_braces_in_literals(repo: Path) -> None:
    load = next(s for s in find_go_surfaces(repo) if s.symbol == "Load")
    assert load.excerpt.startswith("func Load()")
    assert load.excerpt.rstrip().endswith("}")
    assert "return &Config{}, nil" in load.excerpt


def test_kind_filter_and_dispatch(repo: Path) -> None:
    only = find_surfaces(repo, Language.go, {"validator", "nope"})
    assert {s.kind for s in only} == {"validator"}
    # python dispatch exists now and a go repo has no python surfaces
    assert find_surfaces(repo, Language.python) == []


def test_source_root_and_long_excerpt(tmp_path: Path) -> None:
    body = "\n".join(f'\t_ = os.Getenv("K{i}")' for i in range(MAX_EXCERPT_LINES + 5))
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc/env.go").write_text(f"package svc\n\nfunc readAll() {{\n{body}\n}}\n")
    (tmp_path / "other.go").write_text('package main\nfunc main() { _ = os.Getenv("X") }\n')
    found = find_go_surfaces(tmp_path, source_root="svc")
    assert [(s.file, s.symbol) for s in found] == [("svc/env.go", "readAll")]
    assert found[0].excerpt.endswith("// ...")
