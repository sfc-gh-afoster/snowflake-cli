import logging
from zipfile import ZipFile

from requirements.requirement import Requirement
from unittest.mock import ANY, MagicMock, patch

from snowcli.cli.snowpark import package
from snowcli.cli.snowpark.package.utils import NotInAnaconda
from snowcli.utils import SplitRequirements
from tests.testing_utils.fixtures import *


class TestPackage:
    @pytest.mark.parametrize(
        "argument",
        [
            (
                "snowflake-connector-python",
                "Package snowflake-connector-python is available on the Snowflake anaconda \nchannel.",
                "snowcli.cli.snowpark.package.commands",
            ),
            (
                "some-weird-package-we-dont-know",
                "Lookup for package some-weird-package-we-dont-know resulted in some error. \nPlease check the package name and try again",
                "snowcli.cli.snowpark.package.commands",
            ),
        ],
    )
    @patch("tests.test_package.package.manager.utils.requests")
    def test_package_lookup(self, mock_requests, argument, monkeypatch, runner) -> None:
        mock_requests.get.return_value = self.mocked_anaconda_response(
            test_data.anaconda_response
        )

        result = runner.invoke(["snowpark", "package", "lookup", argument[0], "--yes"])

        assert result.exit_code == 0
        assert argument[1] in result.output

    @patch("tests.test_package.package.manager.utils.install_packages")
    @patch("tests.test_package.package.manager.utils.parse_anaconda_packages")
    def test_package_lookup_with_install_packages(
        self, mock_package, mock_install, runner, capfd
    ) -> None:
        mock_package.return_value = SplitRequirements(
            [], [Requirement("some-other-package")]
        )
        mock_install.return_value = (
            True,
            SplitRequirements(
                [Requirement("snowflake-snowpark-python")],
                [Requirement("some-other-package")],
            ),
        )

        result = runner.invoke(
            ["snowpark", "package", "lookup", "some-other-package", "--yes"]
        )
        assert result.exit_code == 0
        assert (
            'include the following in your packages: [<Requirement: \n"snowflake-snowpark-python">]'
            in result.output
        )

    @patch("tests.test_package.package.commands.lookup")
    def test_package_create(
        self, mock_lookup, caplog, temp_dir, dot_packages_directory, runner
    ) -> None:

        mock_lookup.return_value = NotInAnaconda(
            SplitRequirements([], ["some-other-package"]), "totally-awesome-package"
        )

        with caplog.at_level(logging.DEBUG, logger="snowcli.cli.snowpark.package"):
            result = runner.invoke(
                ["snowpark", "package", "create", "totally-awesome-package", "--yes"]
            )

        assert result.exit_code == 0
        assert os.path.isfile("totally-awesome-package.zip")

        zip_file = ZipFile("totally-awesome-package.zip", "r")

        assert (
            ".packages/totally-awesome-package/totally-awesome-module.py"
            in zip_file.namelist()
        )
        os.remove("totally-awesome-package.zip")

    @patch("snowcli.cli.snowpark.package.manager.snow_cli_global_context_manager")
    def test_package_upload(self, mock_ctx_manager, package_file: str, runner) -> None:
        result = runner.invoke(
            ["snowpark", "package", "upload", "-f", package_file, "-s", "stageName"]
        )

        assert result.exit_code == 0
        mock_ctx_manager.get_connection.return_value.upload_file_to_stage.assert_called_with(
            file_path=ANY,
            destination_stage="stageName",
            path="/",
            database=ANY,
            schema=ANY,
            overwrite=False,
            role=ANY,
            warehouse=ANY,
        )

    @staticmethod
    def mocked_anaconda_response(response: dict):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response

        return mock_response
