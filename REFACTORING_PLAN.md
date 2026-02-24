# Pygiskit Refactoring Plan

**Created:** 2026-02-24
**Goal:** Improve code quality from 7.4/10 to 8.5-9.0/10
**Estimated Duration:** 4-6 weeks

---

## Overview

Based on the comprehensive code review, this plan addresses:
1. **Code duplication** (~250 lines in config-driven providers)
2. **Monolithic functions** (451-line run() command)
3. **Inconsistent error handling** (missing exception chaining)
4. **Debug print statements** (should use proper logging)
5. **Magic numbers** (need named constants)

---

## Phase 1: Quick Wins (Week 1)

**Goal:** Low-effort, high-impact improvements
**Estimated Time:** 1 week
**Expected Quality Improvement:** 7.4 → 7.8/10

### Milestone 1.1: Extract Constants & Enable Linting
**Files to Create:**
- `giskit/core/constants.py`

**Files to Modify:**
- `pyproject.toml` (enable ruff B904)
- `giskit/cli/commands/run.py` (use constants)
- `giskit/protocols/ogc_features.py` (use constants)

**Tasks:**
- [ ] Create constants.py with BGT_ALL_LAYERS_THRESHOLD, DEFAULT_GRID_CELL_SIZE_M, etc.
- [ ] Replace magic numbers in run.py
- [ ] Replace magic numbers in ogc_features.py
- [ ] Enable ruff B904 rule (exception chaining)
- [ ] Run ruff check and fix violations
- [ ] Run tests to verify no breakage
- [ ] Commit: "refactor: extract magic numbers to constants, enable B904 rule"

**Acceptance Criteria:**
- ✅ No magic numbers in core code paths
- ✅ Ruff B904 enabled and passing
- ✅ All tests passing

---

### Milestone 1.2: Fix Exception Chaining
**Files to Modify:**
- All files with `raise` statements without `from e`

**Tasks:**
- [ ] Run ruff check to find B904 violations
- [ ] Fix all `raise` statements to use `raise ... from e`
- [ ] Verify proper exception chaining in protocols
- [ ] Run tests to verify error handling still works
- [ ] Commit: "fix: add proper exception chaining (B904)"

**Acceptance Criteria:**
- ✅ All exceptions properly chained
- ✅ Ruff B904 passing
- ✅ Exception tests passing

---

### Milestone 1.3: Replace Print with Logging
**Files to Create:**
- None (use stdlib logging)

**Files to Modify:**
- `giskit/providers/wcs.py` (remove print statements)
- `giskit/protocols/ogc_features.py` (grid walking progress)
- Any other files with print/console.print for debug output

**Tasks:**
- [ ] Add logging setup to each module
- [ ] Replace print() with logger.info/debug/warning
- [ ] Remove debug print statements from WCS provider
- [ ] Add --log-level CLI flag to run command
- [ ] Test logging output at different levels
- [ ] Commit: "feat: replace print statements with proper logging"

**Acceptance Criteria:**
- ✅ No debug print() in production code
- ✅ Logging configurable via CLI flag
- ✅ Log levels appropriate (debug, info, warning, error)

---

### Milestone 1.4: Extract YAML Helper
**Files to Create:**
- `giskit/config/yaml_utils.py`

**Files to Modify:**
- `giskit/config/loader.py`
- `giskit/config/discovery.py`

**Tasks:**
- [ ] Create yaml_utils.py with load_yaml_safe(), save_yaml_safe()
- [ ] Replace YAML loading in loader.py
- [ ] Replace YAML loading in discovery.py
- [ ] Add error handling for invalid YAML
- [ ] Run tests to verify config loading works
- [ ] Commit: "refactor: extract YAML loading to shared helper"

**Acceptance Criteria:**
- ✅ Single YAML loading implementation
- ✅ All config loading uses shared helper
- ✅ Config tests passing

---

## Phase 2: Core Refactoring (Week 2-3)

**Goal:** Eliminate code duplication, improve architecture
**Estimated Time:** 2 weeks
**Expected Quality Improvement:** 7.8 → 8.3/10

### Milestone 2.1: Create ConfigDrivenProvider Base Class
**Files to Create:**
- `giskit/providers/config_driven.py`

**Files to Modify:**
- `giskit/providers/ogc_features.py`
- `giskit/providers/wmts.py`
- `giskit/providers/wcs.py`
- `giskit/providers/multi_protocol.py`
- `giskit/providers/__init__.py`

**Tasks:**
- [ ] Create ConfigDrivenProvider base class
- [ ] Extract get_service_info() to base
- [ ] Extract list_categories() to base
- [ ] Extract get_services_by_category() to base
- [ ] Extract get_metadata() to base
- [ ] Extract config loading to base __init__
- [ ] Refactor OGCFeaturesProvider to inherit from ConfigDrivenProvider
- [ ] Refactor WMTSProvider to inherit from ConfigDrivenProvider
- [ ] Refactor WCSProvider to inherit from ConfigDrivenProvider
- [ ] Update MultiProtocolProvider to use base methods
- [ ] Run unit tests for all providers
- [ ] Run integration tests
- [ ] Commit: "refactor: extract ConfigDrivenProvider base class"

**Acceptance Criteria:**
- ✅ ~250 lines of duplication eliminated
- ✅ All providers inherit from ConfigDrivenProvider
- ✅ All provider tests passing
- ✅ No regression in functionality

**Estimated LOC Reduction:** 200-250 lines

---

### Milestone 2.2: Create ProtocolRegistry
**Files to Create:**
- `giskit/protocols/registry.py`

**Files to Modify:**
- `giskit/protocols/__init__.py`
- `giskit/protocols/ogc_features.py` (register protocol)
- `giskit/protocols/wfs.py` (register protocol)
- `giskit/protocols/wmts.py` (register protocol)
- `giskit/protocols/wcs.py` (register protocol)
- `giskit/protocols/gtfs.py` (register protocol)
- `giskit/protocols/csv_protocol.py` (register protocol)
- `giskit/providers/multi_protocol.py` (use registry)

**Tasks:**
- [ ] Create ProtocolRegistry class
- [ ] Implement register() and create() methods
- [ ] Add protocol registration to each protocol file
- [ ] Refactor MultiProtocolProvider._create_protocol_handler() to use registry
- [ ] Remove 60-line if/elif chain
- [ ] Test protocol instantiation
- [ ] Run all protocol tests
- [ ] Commit: "refactor: introduce ProtocolRegistry pattern"

**Acceptance Criteria:**
- ✅ All protocols registered in registry
- ✅ MultiProtocolProvider uses registry
- ✅ 60-line if/elif chain eliminated
- ✅ Easy to add new protocols

**Estimated LOC Reduction:** 50-60 lines

---

### Milestone 2.3: Centralize HTTP Error Handling
**Files to Modify:**
- `giskit/protocols/base.py`
- `giskit/protocols/ogc_features.py`
- `giskit/protocols/wfs.py`
- `giskit/protocols/wmts.py`
- `giskit/protocols/wcs.py`

**Tasks:**
- [ ] Add _http_get() method to Protocol base class
- [ ] Add _http_post() method to Protocol base class
- [ ] Add _wrap_http_error() abstract method
- [ ] Refactor OGCFeaturesProtocol to use base _http_get()
- [ ] Refactor WFSProtocol to use base _http_get()
- [ ] Refactor WMTSProtocol to use base _http_get()
- [ ] Refactor WCSProtocol to use base _http_get()
- [ ] Run protocol tests
- [ ] Commit: "refactor: centralize HTTP error handling in Protocol base"

**Acceptance Criteria:**
- ✅ Single HTTP request implementation
- ✅ Consistent error wrapping
- ✅ ~50 lines of duplication eliminated
- ✅ Protocol tests passing

**Estimated LOC Reduction:** 40-50 lines

---

## Phase 3: CLI Refactoring (Week 4)

**Goal:** Extract business logic from CLI layer
**Estimated Time:** 1 week
**Expected Quality Improvement:** 8.3 → 8.6/10

### Milestone 3.1: Create RecipeRunner Core Module
**Files to Create:**
- `giskit/core/runner.py`

**Files to Modify:**
- `giskit/cli/commands/run.py`

**Tasks:**
- [ ] Create RecipeRunner class in core/runner.py
- [ ] Extract execute() method (main execution logic)
- [ ] Extract _download_datasets() method
- [ ] Extract _normalize_layer_names() method
- [ ] Extract _add_metadata_layer() method
- [ ] Extract _calculate_origin_point() method
- [ ] Extract _build_metadata_dict() method
- [ ] Add comprehensive docstrings
- [ ] Commit: "refactor: create RecipeRunner in core module"

**Acceptance Criteria:**
- ✅ RecipeRunner class created
- ✅ All business logic extracted from CLI
- ✅ Methods have clear single responsibilities
- ✅ Comprehensive docstrings

**Estimated LOC in New File:** ~300 lines

---

### Milestone 3.2: Refactor CLI to Use RecipeRunner
**Files to Modify:**
- `giskit/cli/commands/run.py`

**Tasks:**
- [ ] Import RecipeRunner in run.py
- [ ] Refactor _execute_recipe() to use RecipeRunner
- [ ] Simplify run() command to orchestration only
- [ ] Remove duplicated business logic
- [ ] Keep CLI-specific code (console output, click decorators)
- [ ] Run CLI tests
- [ ] Test recipe execution end-to-end
- [ ] Commit: "refactor: simplify CLI using RecipeRunner"

**Acceptance Criteria:**
- ✅ run.py reduced from 728 → ~250 lines
- ✅ CLI only handles user interaction
- ✅ Business logic in core/runner.py
- ✅ All CLI tests passing
- ✅ Recipe execution works end-to-end

**Estimated LOC Reduction:** 450 lines (moved to core)

---

### Milestone 3.3: Extract Output Management
**Files to Create:**
- `giskit/core/output.py`

**Files to Modify:**
- `giskit/cli/commands/run.py`

**Tasks:**
- [ ] Create OutputManager class
- [ ] Extract save_layers() method
- [ ] Extract export_ifc() method
- [ ] Extract export_glb() method
- [ ] Extract export_obj() method
- [ ] Simplify run.py output handling
- [ ] Run export tests
- [ ] Commit: "refactor: extract OutputManager for file exports"

**Acceptance Criteria:**
- ✅ OutputManager handles all file I/O
- ✅ run.py further simplified
- ✅ Export logic testable independently
- ✅ All export formats working

**Estimated LOC Reduction:** 100-150 lines (moved to core)

---

## Phase 4: Testing & Validation (Week 5-6)

**Goal:** Improve test coverage, ensure quality
**Estimated Time:** 2 weeks
**Expected Quality Improvement:** 8.6 → 9.0/10

### Milestone 4.1: Add Unit Tests for Core Modules
**Files to Create:**
- `tests/unit/test_runner.py`
- `tests/unit/test_output.py`
- `tests/unit/test_config_driven_provider.py`
- `tests/unit/test_protocol_registry.py`

**Tasks:**
- [ ] Write tests for RecipeRunner.execute()
- [ ] Write tests for RecipeRunner._normalize_layer_names()
- [ ] Write tests for RecipeRunner._calculate_origin_point()
- [ ] Write tests for OutputManager
- [ ] Write tests for ConfigDrivenProvider
- [ ] Write tests for ProtocolRegistry
- [ ] Achieve >80% coverage on new modules
- [ ] Commit: "test: add unit tests for core refactored modules"

**Acceptance Criteria:**
- ✅ >80% coverage on RecipeRunner
- ✅ >80% coverage on OutputManager
- ✅ >80% coverage on ConfigDrivenProvider
- ✅ All edge cases tested

---

### Milestone 4.2: Add Integration Tests
**Files to Create:**
- `tests/integration/test_wmts_provider.py`
- `tests/integration/test_wcs_provider.py`

**Files to Modify:**
- `tests/integration/test_pdok_providers.py`

**Tasks:**
- [ ] Add WMTS provider end-to-end test
- [ ] Add WCS provider end-to-end test
- [ ] Test ConfigDrivenProvider with real configs
- [ ] Test ProtocolRegistry with real protocols
- [ ] Mark slow tests appropriately
- [ ] Commit: "test: add integration tests for WMTS and WCS"

**Acceptance Criteria:**
- ✅ WMTS download tested end-to-end
- ✅ WCS download tested end-to-end
- ✅ Integration tests properly marked
- ✅ All tests passing

---

### Milestone 4.3: Update Documentation
**Files to Create:**
- `docs/architecture.md`
- `docs/adding_providers.md`
- `docs/adding_protocols.md`

**Files to Modify:**
- `README.md`
- `CONTRIBUTING.md`
- `AGENTS.md`

**Tasks:**
- [ ] Write architecture documentation
- [ ] Document Provider/Protocol patterns
- [ ] Document how to add new providers
- [ ] Document how to add new protocols
- [ ] Update README with architecture overview
- [ ] Update CONTRIBUTING with refactoring notes
- [ ] Update AGENTS.md with new module structure
- [ ] Commit: "docs: add architecture and contribution documentation"

**Acceptance Criteria:**
- ✅ Architecture clearly documented
- ✅ Adding providers/protocols documented
- ✅ README updated
- ✅ AGENTS.md reflects new structure

---

### Milestone 4.4: Final Validation
**Tasks:**
- [ ] Run full test suite (unit + integration)
- [ ] Run ruff check --fix
- [ ] Run ruff format
- [ ] Run mypy giskit/
- [ ] Test all example recipes
- [ ] Verify all exports work (GPKG, IFC, GLB, OBJ)
- [ ] Check code coverage report
- [ ] Review REFACTORING_PLAN.md completion
- [ ] Commit: "chore: final validation and code quality checks"

**Acceptance Criteria:**
- ✅ All tests passing (unit + integration)
- ✅ Ruff passing (no violations)
- ✅ Mypy passing (no type errors)
- ✅ >75% code coverage
- ✅ All example recipes working
- ✅ All export formats working

---

## Success Metrics

### Code Quality Improvements
| Metric | Before | Target | Measurement |
|--------|--------|--------|-------------|
| Overall Score | 7.4/10 | 8.5-9.0/10 | Review assessment |
| Code Duplication | 6/10 | 9/10 | Provider code reuse |
| Separation of Concerns | 7/10 | 9/10 | CLI vs core separation |
| Test Coverage | ~60% | >75% | pytest --cov |
| Ruff Violations | ~50 | 0 | ruff check |
| Longest Function | 451 lines | <100 lines | run() command |

### LOC Reduction
| Phase | Reduction | Notes |
|-------|-----------|-------|
| Phase 1 | ~50 lines | Constants, YAML helper |
| Phase 2 | ~300 lines | ConfigDrivenProvider, Registry, HTTP |
| Phase 3 | ~550 lines | RecipeRunner, OutputManager (moved) |
| **Total** | **~900 lines** | Through deduplication & extraction |

### Maintainability Improvements
- ✅ New provider added in <50 lines (vs 200+ before)
- ✅ New protocol added in <100 lines (vs 150+ before)
- ✅ CLI tests easy to write (business logic extracted)
- ✅ Clear onboarding documentation

---

## Risk Mitigation

### Risks & Mitigation Strategies

**Risk 1: Breaking Changes**
- Mitigation: Commit after each milestone
- Mitigation: Run full test suite before each commit
- Mitigation: Test example recipes manually

**Risk 2: Test Coverage Gaps**
- Mitigation: Write tests before refactoring
- Mitigation: Maintain >80% coverage on new code
- Mitigation: Add integration tests for critical paths

**Risk 3: Performance Regression**
- Mitigation: Benchmark recipe execution before/after
- Mitigation: Profile slow tests
- Mitigation: Keep async patterns unchanged

**Risk 4: Configuration Breaking**
- Mitigation: Test with existing YAML configs
- Mitigation: Validate backward compatibility
- Mitigation: Add config migration guide if needed

---

## Rollback Plan

Each milestone has a commit, allowing easy rollback:
```bash
# If Milestone 2.1 breaks something:
git log --oneline  # Find commit before 2.1
git revert <commit-hash>
# OR
git reset --hard <commit-hash>
```

---

## Timeline

```
Week 1: Phase 1 - Quick Wins
├─ Day 1-2: Milestone 1.1 (Constants, B904)
├─ Day 2-3: Milestone 1.2 (Exception Chaining)
├─ Day 3-4: Milestone 1.3 (Logging)
└─ Day 4-5: Milestone 1.4 (YAML Helper)

Week 2-3: Phase 2 - Core Refactoring
├─ Week 2: Milestone 2.1 (ConfigDrivenProvider)
├─ Week 2-3: Milestone 2.2 (ProtocolRegistry)
└─ Week 3: Milestone 2.3 (HTTP Error Handling)

Week 4: Phase 3 - CLI Refactoring
├─ Day 1-3: Milestone 3.1 (RecipeRunner)
├─ Day 3-4: Milestone 3.2 (CLI Refactor)
└─ Day 4-5: Milestone 3.3 (OutputManager)

Week 5-6: Phase 4 - Testing & Validation
├─ Week 5: Milestones 4.1-4.2 (Tests)
├─ Week 6 Day 1-3: Milestone 4.3 (Documentation)
└─ Week 6 Day 4-5: Milestone 4.4 (Final Validation)
```

---

## Notes

- Each milestone should be completed and tested before moving to the next
- Commits should have descriptive messages following conventional commits
- All tests must pass before committing
- Code should be formatted with ruff before committing
- Integration tests should be run before major milestone commits

---

**Status:** Ready to begin
**Next Step:** Commit baseline, start Phase 1 Milestone 1.1
