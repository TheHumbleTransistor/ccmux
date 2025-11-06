# Refactoring Plan: ccwt → ccmux

## Overview
This document outlines the refactoring plan to rename the project from `ccwt` (claude code worktrees) to `ccmux` (claude code multiplexer) and update the architecture to support both main repository instances and worktree instances.

## Phase 1: Project Rename

1. **Rename package directory** from `ccwt/` to `ccmux/`
2. **Update pyproject.toml**:
   - Package name: ccwt → ccmux
   - Script entry point: ccmux = "ccmux.cli:main"
   - Update description and package includes
3. **Update all import statements** in Python files
4. **Update state directory** from `~/.ccwt` to `~/.ccmux`
5. **Change default session name** from "ccwt" to "ccmux"
6. **Update README.md** with new name and command examples
7. **Update install.sh** with new references

## Phase 2: Instance/Worktree Architecture Changes

### State Structure Update
Add boolean field to track instance type:
```json
{
  "sessions": {
    "session-name": {
      "tmux_session_id": "$0",
      "instances": {  // renamed from "worktrees"
        "instance-name": {
          "repo_path": "/path/to/repo",
          "instance_path": "/path/to/repo or /path/to/repo/.worktrees/name",
          "is_worktree": true | false,  // NEW boolean field
          "tmux_window_id": "@1"
        }
      }
    }
  }
}
```

### New Command Implementation
1. **Add `-w/--worktree` flag** to `new` command
2. **Main repo instance logic** (when flag not used):
   - Create instance using main repo path
   - Check if any existing instance has `is_worktree: false` for this repo
   - If yes: prompt user "Main repo already in use. Create a worktree instead? [Y/n]"
   - If user confirms: create worktree automatically
   - Set `is_worktree: false` for main repo instances
3. **Worktree instance logic** (with `-w` flag or after prompt):
   - Create worktree in `.worktrees/<name>` directory
   - Set `is_worktree: true` for worktree instances

## Phase 3: List Command Updates

1. **Rename column** "Worktree" → "Instance"
2. **Add "Type" column** with text values:
   - Show "worktree" when `is_worktree: true`
   - Show "root" when `is_worktree: false`
3. **Updated column structure**:
   - Repository (yellow) - repo name
   - Instance (cyan) - instance name
   - Type (green) - "root" or "worktree"
   - Branch (magenta) - current branch
   - Status (bold) - ● Active / ○ Inactive
   - Tmux Window (blue) - window name if active
   - Path (dim) - full instance path

## Phase 4: Terminology Updates

- Replace "worktree" → "instance" in user-facing messages
- Internal state key: "worktrees" → "instances"
- Keep internal function names that refer to git worktrees
- Update docstrings and comments
- Update command help descriptions

## Phase 5: Implementation Details

### Key Functions to Update

1. **state.py**:
   - Rename `worktrees` key to `instances` in state structure
   - Add `is_worktree` field handling
   - Update all accessor methods

2. **cli.py - new command**:
   - Add `-w/--worktree` flag
   - Implement main repo detection logic
   - Add interactive prompt for conflicts
   - Set `is_worktree` appropriately

3. **cli.py - list command**:
   - Update table columns
   - Add Type column with "root"/"worktree" text
   - Change terminology in output

## Phase 6: Testing with Pytest

### Create/Update Test Files

1. **test_state.py** - State management tests:
   - Test `is_worktree` field persistence
   - Test instances vs worktrees key migration
   - Test finding main repo instances

2. **test_cli.py** - CLI command tests:
   - Test `new` command with/without `-w` flag
   - Test main repo conflict detection
   - Test list command output format
   - Mock interactive prompts and verify behavior

3. **test_integration.py** (new) - Integration tests:
   ```python
   def test_create_main_repo_instance():
       # Test creating instance without -w flag

   def test_create_worktree_instance():
       # Test creating instance with -w flag

   def test_main_repo_conflict_prompt():
       # Test prompt when main repo already in use

   def test_list_mixed_instances():
       # Test list output with both main and worktree instances

   def test_instance_activation_deactivation():
       # Test activate/deactivate for both instance types
   ```

### Test Coverage Areas
- State file migration (ccwt → ccmux)
- Instance creation (main repo vs worktree)
- Conflict detection and prompting
- List command formatting
- Session management
- Command aliases and flags
- Error handling for edge cases

## Phase 7: Manual Validation

1. Create main repo instance without flag
2. Attempt to create second main repo instance (verify prompt)
3. Create worktree with `-w` flag
4. Verify list command shows "root" and "worktree" in Type column
5. Test all commands with both instance types
6. Verify tmux session management

## Files to Modify (13 files)

- **Rename directory**: `ccwt/` → `ccmux/`
- **Python files** (6): `__init__.py`, `__main__.py`, `cli.py`, `state.py`, `tests/test_state.py`, `tests/test_cli.py`
- **New test file** (1): `tests/test_integration.py`
- **Config** (1): `pyproject.toml`
- **Docs** (2): `README.md`, `install.sh`
- **Update ~100+ references** to 'ccwt' across all files

## User Decisions Made

- **State Migration**: Manual migration (user is the only user currently)
- **Main Repo Conflict**: Interactive prompt when main repo is already in use
- **Type Indicator**: "Type" column with "root" or "worktree" text
- **Default Session Name**: Change from "ccwt" to "ccmux"
- **State Field**: Use boolean `is_worktree` field