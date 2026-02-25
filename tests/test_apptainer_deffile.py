"""Tests for apptainer definition file generation."""

from __future__ import annotations

from euler_files.apptainer.deffile import generate_def_file


class TestGenerateDefFile:
    def test_basic_output(self) -> None:
        result = generate_def_file(
            venv_name="my-env",
            venv_source_path="/home/user/venvs/my-env",
            python_version="3.11.5",
        )

        assert "Bootstrap: docker" in result
        assert "From: python:3.11-slim" in result
        assert "VenvName my-env" in result
        assert "PythonVersion 3.11.5" in result

    def test_files_section(self) -> None:
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/path/to/venv",
            python_version="3.12.0",
        )

        assert "/path/to/venv /opt/venv" in result

    def test_custom_container_path(self) -> None:
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/path/to/venv",
            python_version="3.11.5",
            container_venv_path="/app/venv",
        )

        assert "/path/to/venv /app/venv" in result
        assert 'VIRTUAL_ENV="/app/venv"' in result
        assert '"/app/venv/bin:$PATH"' in result

    def test_custom_base_image(self) -> None:
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/venv",
            python_version="3.11.5",
            base_image_template="registry.local/python:{version}",
        )

        assert "From: registry.local/python:3.11" in result

    def test_post_fixups_present(self) -> None:
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/venv",
            python_version="3.11.5",
        )

        # Check that path fixup commands are present
        assert "pyvenv.cfg" in result
        assert "sed -i" in result
        assert "ln -sf" in result
        assert "PYTHON_MM=" in result

    def test_environment_section(self) -> None:
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/venv",
            python_version="3.11.5",
        )

        assert "export VIRTUAL_ENV=" in result
        assert "export PATH=" in result

    def test_runscript(self) -> None:
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/venv",
            python_version="3.11.5",
        )

        assert 'exec python "$@"' in result

    def test_full_version_in_template(self) -> None:
        """Test that {full_version} can be used in base image template."""
        result = generate_def_file(
            venv_name="test",
            venv_source_path="/venv",
            python_version="3.11.5",
            base_image_template="python:{full_version}",
        )

        assert "From: python:3.11.5" in result
