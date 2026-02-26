"""Apptainer definition file template generation."""

from __future__ import annotations

# Tarball-based template: copies a single .tar file instead of the directory
# tree. This is dramatically faster on shared HPC filesystems (GPFS/Lustre)
# because tar reads sequentially (one open, one stream) while %files on a
# directory does per-file stat+open+read — tens of thousands of metadata ops.
APPTAINER_DEF_TEMPLATE = """\
Bootstrap: docker
From: {base_image}

%labels
    Author euler-files
    VenvName {venv_name}
    PythonVersion {python_version}

%files
    {tar_path} /opt/venv.tar

%post
    set -e

    CONTAINER_VENV="{container_venv_path}"
    PYTHON_MM="{python_major_minor}"

    # Extract the pre-packed venv tarball
    mkdir -p "$CONTAINER_VENV"
    tar xf /opt/venv.tar -C "$CONTAINER_VENV" --strip-components=1
    rm -f /opt/venv.tar

    # Fix pyvenv.cfg to point to the container's system Python
    PYVENV_CFG="$CONTAINER_VENV/pyvenv.cfg"
    if [ -f "$PYVENV_CFG" ]; then
        PYTHON_BIN=$(dirname $(which python$PYTHON_MM 2>/dev/null || which python3))
        sed -i "s|^home = .*|home = $PYTHON_BIN|" "$PYVENV_CFG"
    fi

    # Fix shebangs in venv bin/ scripts
    VENV_BIN="$CONTAINER_VENV/bin"
    if [ -d "$VENV_BIN" ]; then
        find "$VENV_BIN" -type f -exec \\
            sed -i "1s|^#!.*/python[0-9.]*|#!$CONTAINER_VENV/bin/python|" {{}} +
    fi

    # Ensure python symlinks point to the container's Python
    SYSTEM_PYTHON=$(which python$PYTHON_MM 2>/dev/null || which python3)
    rm -f "$CONTAINER_VENV/bin/python" "$CONTAINER_VENV/bin/python3"
    ln -sf "$SYSTEM_PYTHON" "$CONTAINER_VENV/bin/python"
    ln -sf "$SYSTEM_PYTHON" "$CONTAINER_VENV/bin/python3"

    # Fix activate script VIRTUAL_ENV path
    if [ -f "$CONTAINER_VENV/bin/activate" ]; then
        sed -i "s|VIRTUAL_ENV=.*|VIRTUAL_ENV=\\"$CONTAINER_VENV\\"|" "$CONTAINER_VENV/bin/activate"
    fi

%environment
    export VIRTUAL_ENV="{container_venv_path}"
    export PATH="{container_venv_path}/bin:$PATH"

%runscript
    exec python "$@"
"""


def generate_def_file(
    venv_name: str,
    tar_path: str,
    python_version: str,
    container_venv_path: str = "/opt/venv",
    base_image_template: str = "python:{version}-slim",
) -> str:
    """Generate an Apptainer definition file for packaging a venv.

    The definition file expects a pre-packed tarball of the venv directory
    (created by the build step). This avoids per-file metadata operations
    on slow shared filesystems — tar reads sequentially, which is orders
    of magnitude faster than copying thousands of individual files.

    Args:
        venv_name: Name of the venv (used in labels).
        tar_path: Absolute path to the venv tarball (.tar file).
        python_version: Full Python version string (e.g. "3.11.5").
        container_venv_path: Where the venv will live inside the container.
        base_image_template: Docker image template ({version} = major.minor).
    """
    python_major_minor = ".".join(python_version.split(".")[:2])
    base_image = base_image_template.format(
        version=python_major_minor,
        full_version=python_version,
    )
    return APPTAINER_DEF_TEMPLATE.format(
        base_image=base_image,
        venv_name=venv_name,
        tar_path=tar_path,
        python_version=python_version,
        python_major_minor=python_major_minor,
        container_venv_path=container_venv_path,
    )
