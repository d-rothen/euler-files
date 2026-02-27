# euler-files

Manage environment-variable caches on HPC clusters by syncing from slow
persistent storage to fast scratch directories.

On clusters like ETH Euler, persistent home directories live on slow
network-attached storage while per-job `$SCRATCH` sits on fast local or
parallel filesystems. Tools like HuggingFace, PyTorch Hub, and pip all write
multi-gigabyte caches under `$HOME/.cache/...` by default. Every job that reads
these caches pays the penalty of slow metadata ops on the shared filesystem.

**euler-files** fixes this by:

1. Syncing cache directories to `$SCRATCH` with rsync (parallel, locked,
   smart-skipped).
2. Exporting the relevant environment variables so tools read from scratch.
3. Optionally packaging Python venvs into Apptainer/Singularity `.sif` images
   for reproducible, fast container execution.

## Installation

```bash
pip install .
# or in development mode:
pip install -e '.[dev]'
```

Requires Python 3.8+ and the following system tools:

- `rsync` (available on virtually all HPC systems)
- `tar` (for Apptainer builds)
- `apptainer` (only for container features; usually loaded via `module load apptainer`)

## Quick start

```bash
# 1. Run the interactive setup wizard
euler-files init

# 2. Sync caches to scratch and export env vars (use eval!)
eval "$(euler-files sync)"

# 3. Check sync status
euler-files status
```

For daily use, set up the shell helper so you only have to type `ef`:

```bash
# Add to ~/.bashrc or ~/.zshrc:
eval "$(euler-files shell-init)"

# Then in any session:
ef              # syncs + exports
ef status       # shows status table
ef push         # reverse-syncs scratch back to persistent storage
```

## How it works

### The sync cycle

```
  Persistent storage          $SCRATCH
  (slow home/project)         (fast local/parallel FS)
  ┌──────────────┐            ┌──────────────┐
  │ ~/.cache/    │  ──rsync─> │ $SCRATCH/     │
  │   huggingface│            │  .cache/      │
  │   torch      │            │   euler-files/│
  │   pip        │            │     HF_HOME/  │
  └──────────────┘            │     TORCH_HOME│
                              └──────────────┘
                                     │
                              export HF_HOME=$SCRATCH/...
                              export TORCH_HOME=$SCRATCH/...
```

`euler-files sync` runs rsync for each configured variable in parallel (up to
`parallel_jobs` threads), then prints `export VAR=<scratch-path>` lines to
stdout. Wrapping it in `eval "$(...)"` applies those exports to the current
shell.

All progress messages go to stderr so they never pollute the `eval`-captured
output.

### Smart-skip markers

After a successful sync, a JSON marker file (`.VAR_NAME.synced`) is written
to the scratch cache root. On the next sync, rsync is skipped if:

1. The marker is younger than `skip_if_fresh_seconds` (default 3600 = 1 hour).
2. The source directory's top-level mtime hasn't increased (checks the
   directory itself and all immediate children).

Deep changes inside the tree are not detected by the marker — but rsync itself
handles those efficiently via its own delta-transfer algorithm. The marker only
avoids the overhead of *launching* rsync when nothing has changed.

Use `--force` to bypass smart-skip.

### Per-variable locking

Each variable gets its own lock file (`.VAR_NAME.lock`) using `flock`. If two
jobs try to sync the same variable simultaneously, one waits (up to
`lock_timeout_seconds`). This prevents partial or corrupted syncs on shared
scratch directories.

## Commands

### `euler-files init`

Interactive wizard that:

- Detects `$SCRATCH` automatically
- Presents preset env vars (HF_HOME, TORCH_HOME, PIP_CACHE_DIR, etc.) with
  descriptions
- Lets you pick which ones to manage and configure their source paths
- Warns about overlapping paths (e.g. `XDG_CACHE_HOME` contains `HF_HOME`)
- Offers advanced settings: parallel jobs, lock timeout, smart-skip threshold
- Saves config to `~/.euler-files.json`

### `euler-files sync [OPTIONS]`

Syncs caches from persistent storage to scratch.

| Option      | Description                                    |
|-------------|------------------------------------------------|
| `--dry-run` | Show what would be synced without doing it     |
| `--force`   | Ignore smart-skip markers and force rsync      |
| `--var VAR` | Sync only specific variable(s); repeatable     |
| `--verbose` | Show rsync details on stderr                   |

**Usage in scripts/jobs:**

```bash
eval "$(euler-files sync)"
```

**Usage in SLURM job scripts:**

```bash
#!/bin/bash
#SBATCH --job-name=training
#SBATCH ...

eval "$(euler-files sync)"

python train.py
```

### `euler-files status`

Displays a rich table showing:

- Source and scratch sizes (via `du -sh`)
- Last sync time and age
- Status: `fresh` (green), `stale` (yellow), `not synced` (red), or
  `source missing` (yellow)
- Total scratch usage

### `euler-files push [OPTIONS]`

Reverse sync: copies modified files from scratch back to persistent storage.
Useful after a job downloads new models or data to scratch.

| Option      | Description                              |
|-------------|------------------------------------------|
| `--var VAR` | Push only specific variable(s)           |
| `--dry-run` | Show what would be pushed                |

Also updates sync markers so subsequent syncs know the data is fresh.

### `euler-files migrate [WHAT] [OPTIONS]`

Moves a cache directory (or apptainer directory) to a new location. This is
useful when reorganizing storage or moving between project directories.

| Option        | Description                                  |
|---------------|----------------------------------------------|
| `WHAT`        | Variable name or field (`venv_base`, `sif_store`); interactive if omitted |
| `--to PATH`   | New location; prompted if omitted            |
| `--dry-run`   | Show what would be done                      |
| `--no-delete` | Keep old directory after migration           |
| `--yes`       | Skip confirmation prompt                     |

Migration steps:

1. rsync with `--delete` to the new location
2. Fix venv internal paths if migrating `venv_base` (rewrites shebangs and
   activate scripts)
3. Update config
4. Record migration in config history
5. Optionally delete old directory

### `euler-files shell-init [--shell bash|zsh|fish]`

Outputs a shell function `ef` for convenient use. Add to your shell rc file:

```bash
# Bash/Zsh:
eval "$(euler-files shell-init)"

# Fish:
eval (euler-files shell-init --shell fish)
```

The `ef` function:

- `ef` or `ef sync` — runs sync with eval (exports env vars into current shell)
- `ef status` — shows status
- `ef push` — reverse sync
- Any other subcommand is passed through to `euler-files`

## Apptainer support

euler-files can also build and manage Apptainer (Singularity) container images
from Python virtual environments. This is useful for packaging ML environments
into portable `.sif` files.

### `euler-files apptainer init`

Interactive wizard that configures:

- **venv_base**: directory containing your venvs (supports `$ENV_VAR` syntax)
- **sif_store**: persistent storage for built `.sif` files
- **scratch_sif_dir**: scratch location for synced `.sif` files
- **base_image**: Docker image template (default: `python:{version}-slim`)
- **container_venv_path**: path inside the container (default: `/opt/venv`)
- **build_args**: extra flags for `apptainer build` (default: `["--fakeroot"]`)

### `euler-files apptainer build [VENV_NAME] [OPTIONS]`

Builds a `.sif` image from a Python venv.

| Option      | Description                              |
|-------------|------------------------------------------|
| `VENV_NAME` | Venv to build; interactive picker if omitted |
| `--force`   | Rebuild even if `.sif` already exists    |
| `--dry-run` | Show definition file and commands without building |

**Build pipeline:**

1. **Tar** — Pre-packs the venv into a tarball. This is a critical optimization
   for shared HPC filesystems (GPFS/Lustre): Apptainer's `%files` directive
   does a per-file `stat`+`open`+`read` for every file in the venv (often tens
   of thousands), while tar reads sequentially in a single stream. The
   difference can be orders of magnitude.
2. **Generate** — Creates an Apptainer definition file that extracts the
   tarball, fixes shebangs, rewires `pyvenv.cfg`, and sets up the environment.
3. **Build** — Runs `apptainer build` to produce the `.sif` file.
4. **Cleanup** — Removes the tarball (in a `finally` block, so it's cleaned up
   even on failure).

### `euler-files apptainer sync [OPTIONS]`

Syncs `.sif` images from persistent storage to scratch.

| Option         | Description                                |
|----------------|---------------------------------------------|
| `--dry-run`    | Show what would be synced                   |
| `--force`      | Ignore freshness checks                     |
| `--image NAME` | Sync only specific image(s); repeatable     |

Uses single-file rsync (no trailing-slash semantics) optimized for large files
with resumable partial transfers.

### `euler-files apptainer prune [IMAGE_NAME] [OPTIONS]`

Removes venvs, `.sif` images, or both.

| Option      | Description                                         |
|-------------|-----------------------------------------------------|
| `IMAGE_NAME`| Image to prune; interactive picker if omitted       |
| `--mode`    | `both` (default), `venv`, or `sif`                  |
| `--dry-run` | Show what would be deleted                          |
| `--yes`     | Skip confirmation prompt                            |

### `euler-files apptainer fixup [VENV_NAME] [OPTIONS]`

Fixes venv internal paths after manually moving the venv base directory.
Rewrites `bin/activate` VIRTUAL_ENV and all shebangs in `bin/*` scripts.
Fixes a single venv if `VENV_NAME` is given, otherwise fixes all venvs.

| Option      | Description                                |
|-------------|--------------------------------------------|
| `VENV_NAME` | Single venv to fix; all if omitted         |
| `--dry-run` | Show what would be fixed                   |

## Configuration

Config lives at `~/.euler-files.json`. It is created by `euler-files init` and
updated by other commands. You can also edit it by hand.

### Fully annotated example

```jsonc
{
  // Config format version. Must be 1. euler-files will refuse to load
  // configs with a different version number.
  "version": 1,

  // Root of the fast scratch filesystem. Supports $ENV_VAR syntax —
  // expanded at runtime, not stored literally. This is typically "$SCRATCH"
  // on ETH Euler or similar HPC systems.
  "scratch_base": "$SCRATCH",

  // Subdirectory under scratch_base where euler-files stores its synced
  // caches, marker files, and lock files. Each managed variable gets its
  // own subdirectory here (e.g. $SCRATCH/.cache/euler-files/HF_HOME/).
  "cache_root": ".cache/euler-files",

  // ── Managed environment variables ──────────────────────────────────
  // Each key is an env var name. When synced, euler-files will:
  //   1. rsync "source" -> $SCRATCH/.cache/euler-files/<VAR_NAME>/
  //   2. Print: export <VAR_NAME>=$SCRATCH/.cache/euler-files/<VAR_NAME>
  "vars": {
    "HF_HOME": {
      // Absolute path to the persistent source directory. This is where
      // HuggingFace stores models, datasets, and tokenizers by default.
      "source": "/cluster/home/jdoe/.cache/huggingface",

      // Set to false to temporarily skip this variable during sync
      // without removing it from the config.
      "enabled": true
    },
    "TORCH_HOME": {
      "source": "/cluster/home/jdoe/.cache/torch",
      "enabled": true
    },
    "PIP_CACHE_DIR": {
      "source": "/cluster/home/jdoe/.cache/pip",

      // Disabled: won't be synced unless you flip this to true or
      // explicitly pass --var PIP_CACHE_DIR.
      "enabled": false
    }
  },

  // ── rsync options ──────────────────────────────────────────────────
  // Extra arguments appended to every rsync invocation. Useful for
  // SSH tunneling, bandwidth limits, or exclude patterns.
  // Example: ["--bwlimit=50000", "--exclude", "*.tmp"]
  "rsync_extra_args": [],

  // ── Concurrency ────────────────────────────────────────────────────
  // Maximum number of variables synced in parallel. Each variable gets
  // its own thread + rsync process. Set to 1 for serial execution.
  "parallel_jobs": 4,

  // ── Locking ────────────────────────────────────────────────────────
  // Maximum time (seconds) to wait for a per-variable flock before
  // giving up. Prevents deadlocks when multiple jobs sync simultaneously.
  // The lock uses polling with exponential backoff (not signals), so it
  // works safely inside the thread pool.
  "lock_timeout_seconds": 300,

  // ── Smart-skip ─────────────────────────────────────────────────────
  // If a sync marker is younger than this many seconds AND the source
  // directory's top-level mtime hasn't changed, rsync is skipped
  // entirely. Set to 0 to disable smart-skip (always run rsync).
  //
  // Note: only top-level changes (directory mtime + immediate children
  // mtime) are detected. Deep changes inside subdirectories won't
  // invalidate the marker — but rsync itself handles those efficiently
  // with its delta-transfer algorithm.
  "skip_if_fresh_seconds": 3600,

  // ── Apptainer container management (optional) ──────────────────────
  // This entire section is optional. Omit it if you don't use Apptainer.
  // Run 'euler-files apptainer init' to set it up interactively.
  "apptainer": {
    // Directory containing your Python virtual environments.
    // Supports $ENV_VAR syntax (expanded at runtime).
    "venv_base": "/cluster/home/jdoe/venvs",

    // Persistent storage for built .sif files. These survive job
    // termination and scratch cleanup.
    "sif_store": "/cluster/home/jdoe/.apptainer/sif",

    // Scratch location where .sif files are synced for fast access
    // during jobs. Same idea as the cache sync above.
    "scratch_sif_dir": "$SCRATCH/.cache/euler-files/sif",

    // Docker base image template for Apptainer builds. The placeholder
    // {version} is replaced with the Python major.minor from the venv
    // (e.g. "3.11"). You can use any Docker image here.
    "base_image": "python:{version}-slim",

    // Canonical path where the venv is mounted inside the container.
    // The definition file extracts the tarball here and fixes all paths
    // to match.
    "container_venv_path": "/opt/venv",

    // Extra arguments for 'apptainer build'. Common values:
    //   --fakeroot  — build without root (default)
    //   --nv        — pass through NVIDIA GPU drivers
    //   --force     — overwrite existing .sif
    "build_args": ["--fakeroot"],

    // ── Built images ─────────────────────────────────────────────────
    // Populated automatically by 'euler-files apptainer build'.
    // You generally don't edit this by hand.
    "images": {
      "my-ml-env": {
        // Name of the source venv directory under venv_base.
        "venv_name": "my-ml-env",

        // Python version detected from pyvenv.cfg at build time.
        "python_version": "3.11.5",

        // Filename of the .sif in sif_store.
        "sif_filename": "my-ml-env.sif",

        // Unix timestamp of when this image was last built.
        "built_at": 1700000000.0,

        // Set to false to skip this image during 'apptainer sync'.
        "enabled": true
      }
    }
  },

  // ── Migration history (optional) ───────────────────────────────────
  // Recorded automatically by 'euler-files migrate'. Each entry tracks
  // a directory move. Useful for auditing and debugging.
  "migrations": [
    {
      "old_path": "/cluster/home/jdoe/.cache/huggingface",
      "new_path": "/cluster/project/ml-data/huggingface",
      "migrated_at": 1700000000.0,

      // Which config field was updated: "source" for env var migrations,
      // "venv_base" or "sif_store" for apptainer field migrations.
      "field_name": "source",

      // For env var migrations: the variable name. Empty string for
      // apptainer field migrations.
      "var_name": "HF_HOME"
    }
  ]
}
```

> **Note:** The config file is plain JSON (not JSONC). The comments above are
> for documentation only. Do not copy them into your actual config file.

### Config path resolution

- Config is always at `~/.euler-files.json`
- `scratch_base` and `apptainer.venv_base` support `$ENV_VAR` syntax and `~`
  expansion (resolved at runtime)
- All other paths are stored as absolute literals

## Congruency checks

On every `sync`, `push`, `status`, and `build`, euler-files checks that your
current environment variables match the config. If `$HF_HOME` is already set to
a different path than what the config has as its source, you'll see a warning
like:

```
[WARN] HF_HOME is set to /some/other/path but config source is
       /cluster/home/jdoe/.cache/huggingface
```

This catches stale `.bashrc` exports that conflict with euler-files management.

## Exit codes

| Code | Meaning                                              |
|------|------------------------------------------------------|
| 0    | Success                                              |
| 1    | One or more syncs/pushes failed (partial failure)    |
| 2    | Configuration error (file not found, version mismatch, etc.) |

## Quirks and things to know

- **stdout vs stderr**: `euler-files sync` prints *only* `export` statements to
  stdout. Everything else (progress, warnings, errors) goes to stderr. This is
  by design — `eval "$(euler-files sync)"` must not accidentally eval status
  messages.

- **rsync trailing slash**: Internally, source paths always get a trailing `/`
  appended so rsync copies *contents* into the target, not the source directory
  itself as a subdirectory.

- **Marker mtime depth**: Smart-skip only checks mtime of the directory itself
  and its immediate children (depth 0 + 1). If you add a file three levels
  deep, the marker won't notice — but rsync will still transfer it correctly
  when the marker eventually expires or you use `--force`.

- **Lock polling**: Locking uses a polling loop with exponential backoff rather
  than `signal.alarm`, because the sync runs inside a `ThreadPoolExecutor` where
  signal-based timeouts don't work.

- **rsync exit codes 23 and 24** (partial transfer / vanished files) are treated
  as warnings, not errors. This is common on shared filesystems where files may
  appear or disappear during a sync.

- **Tarball cleanup**: When building Apptainer images, the intermediate tarball
  (which can be multi-GB) is always cleaned up in a `finally` block, even if the
  build fails.

- **Disabled variables** are kept in config but skipped during sync. They are
  *not* exported. Use `--var VAR_NAME` to force-sync a disabled variable.

- **Config version**: The config has a `version` field (currently `1`).
  euler-files refuses to load configs with a mismatched version — you'll need to
  re-run `euler-files init`.

- **Fish shell**: The generated `ef` function has slightly different syntax for
  Fish. Use `euler-files shell-init --shell fish`.

## Typical HPC workflow

### Cache syncing

```bash
# One-time setup (interactive)
euler-files init

# Optional: set up shell integration
echo 'eval "$(euler-files shell-init)"' >> ~/.bashrc

# In your SLURM job script:
#!/bin/bash
#SBATCH --job-name=train
#SBATCH --gpus=1
#SBATCH --mem=64G
#SBATCH --time=24:00:00

# Sync caches to scratch (fast local disk)
eval "$(euler-files sync)"

# Now HF_HOME, TORCH_HOME, etc. point to scratch
python train.py --model bert-large ...

# After training, push any newly downloaded artifacts back
euler-files push
```

### Apptainer images

Apptainer (formerly Singularity) images let you freeze a Python environment
into a single portable `.sif` file. This is useful when you want reproducible
runs without re-syncing thousands of venv files, or when you need to run on
nodes where installing packages is impractical.

```bash
# ── One-time setup ────────────────────────────────────────────────────

# 1. Create a venv with uv (or python -m venv / virtualenv)
uv venv ~/venvs/my-ml-env
uv pip install --python ~/venvs/my-ml-env torch transformers datasets

# 2. Configure apptainer support (interactive wizard)
euler-files apptainer init
# → asks for venv_base (e.g. ~/venvs), sif_store, scratch_sif_dir, etc.

# 3. Build a .sif image from the venv
#    This tars the venv first (fast sequential I/O), then runs apptainer build.
euler-files apptainer build my-ml-env

# 4. Sync the .sif to scratch for fast job-time access
euler-files apptainer sync


# ── In your SLURM job script ─────────────────────────────────────────

#!/bin/bash
#SBATCH --job-name=train
#SBATCH --gpus=1
#SBATCH --mem=64G
#SBATCH --time=24:00:00

# Load apptainer (cluster-specific)
module load apptainer

# Sync caches AND .sif images to scratch
eval "$(euler-files sync)"
euler-files apptainer sync

# Run your script inside the container
# The .sif's runscript does: exec python "$@"
SIF="$SCRATCH/.cache/euler-files/sif/my-ml-env.sif"
apptainer run --nv "$SIF" train.py --model bert-large ...

# Or get an interactive shell inside the container
apptainer shell --nv "$SIF"


# ── Updating the environment ─────────────────────────────────────────

# Install new packages into the venv
uv pip install --python ~/venvs/my-ml-env accelerate

# Rebuild the image (--force overwrites the existing .sif)
euler-files apptainer build my-ml-env --force

# Re-sync to scratch
euler-files apptainer sync --force


# ── Housekeeping ──────────────────────────────────────────────────────

# Remove an old venv + its .sif
euler-files apptainer prune my-old-env

# Remove only the .sif (keep the venv)
euler-files apptainer prune my-old-env --mode sif

# After moving your venv directory, fix internal paths
euler-files migrate venv_base --to /new/path/to/venvs
# migrate handles rsync + shebang/activate fixup automatically

# Or fix paths manually without migrating
euler-files apptainer fixup
```

**Why the tarball step matters:** On shared HPC filesystems (GPFS, Lustre),
metadata operations are expensive. A typical ML venv contains 30,000+ files.
Apptainer's `%files` directive copies each file individually — that's 30,000
`stat` + `open` + `read` calls on the shared FS. Pre-packing into a tarball
turns this into a single sequential read, which can be 10-100x faster.

## License

MIT
