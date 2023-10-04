import os
import pytest
from textwrap import dedent
from unittest import mock

from snowcli.cli.nativeapp.manager import (
    CouldNotDropObjectError,
    NativeAppManager,
    ApplicationAlreadyExistsError,
    UnexpectedOwnerError,
    SPECIAL_COMMENT,
    LOOSE_FILES_MAGIC_VERSION,
)
from snowcli.cli.stage.diff import DiffResult
from snowflake.connector.cursor import DictCursor


from tests.testing_utils.fixtures import *

NATIVEAPP_MODULE = "snowcli.cli.nativeapp.manager"
NATIVEAPP_MANAGER_EXECUTE = f"{NATIVEAPP_MODULE}.NativeAppManager._execute_query"

mock_snowflake_yml_file = dedent(
    """\
        definition_version: 1
        native_app:
            name: myapp

            source_stage:
                app_src.stage

            artifacts:
                - setup.sql
                - app/README.md
                - src: app/streamlit/*.py
                  dest: ui/

            application:
                name: myapp
                role: app_role
                warehouse: app_warehouse
                debug: true

            package:
                name: app_pkg
                scripts:
                    - shared_content.sql
    """
)

mock_project_definition_override = {
    "native_app": {
        "application": {
            "name": "sample_application_name",
            "role": "sample_application_role",
        },
        "package": {
            "name": "sample_package_name",
            "role": "sample_package_role",
        },
    }
}


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
@mock.patch(f"{NATIVEAPP_MODULE}.stage_diff")
@mock.patch(f"{NATIVEAPP_MODULE}.sync_local_diff_with_stage")
def test_sync_deploy_root_with_stage(
    mock_local_diff_with_stage, mock_stage_diff, mock_execute, temp_dir, mock_cursor
):
    mock_execute.return_value = mock_cursor([{"CURRENT_ROLE()": "old_role"}], [])
    mock_diff_result = DiffResult(different="setup.sql")
    mock_stage_diff.return_value = mock_diff_result
    mock_local_diff_with_stage.return_value = None
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    native_app_manager = NativeAppManager()
    assert mock_diff_result.has_changes()
    native_app_manager.sync_deploy_root_with_stage("new_role")

    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role new_role"),
        mock.call(f"create schema if not exists app_pkg.app_src"),
        mock.call(
            f"""
                    create stage if not exists app_pkg.app_src.stage
                    encryption = (TYPE = 'SNOWFLAKE_SSE')"""
        ),
        mock.call("use role old_role"),
    ]
    assert mock_execute.mock_calls == expected
    mock_stage_diff.assert_called_once_with(
        native_app_manager.deploy_root, "app_pkg.app_src.stage"
    )
    mock_local_diff_with_stage.assert_called_once_with(
        role="new_role",
        deploy_root_path=native_app_manager.deploy_root,
        diff_result=mock_diff_result,
        stage_path="app_pkg.app_src.stage",
    )


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_drop_object(mock_execute, temp_dir, mock_cursor):
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        mock_cursor(["row"], []),
        mock_cursor(
            [
                {
                    "name": "sample_package_name",
                    "owner": "sample_package_role",
                    "blank": "blank",
                    "comment": "GENERATED_BY_SNOWCLI",
                }
            ],
            [],
        ),
        mock_cursor(["row"], []),
        mock_cursor(["row"], []),
    ]

    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    native_app_manager = NativeAppManager()
    native_app_manager.drop_object(
        object_name="sample_package_name",
        object_role="sample_package_role",
        object_type="package",
        query_dict={
            "show": "show application packages like",
            "drop": "drop application package",
        },
    )
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role sample_package_role"),
        mock.call("show application packages like 'sample_package_name'"),
        mock.call("drop applicatin package sample_package_name"),
        mock.call("use role old_role"),
    ]
    mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_drop_object_no_show_object(mock_execute, temp_dir, mock_cursor):
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        mock_cursor(["row"], []),
        mock_cursor([], []),
        mock_cursor(["row"], []),
    ]
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )
    native_app_manager = NativeAppManager()
    with pytest.raises(
        CouldNotDropObjectError,
        match="Role sample_package_role does not own any application package with the name sample_package_name!",
    ):
        native_app_manager.drop_object(
            object_name="sample_package_name",
            object_role="sample_package_role",
            object_type="package",
            query_dict={"show": "show application packages like"},
        )
        expected = [
            mock.call("select current_role()", cursor_class=DictCursor),
            mock.call("use role sample_package_role"),
            mock.call("show application packages like 'sample_package_name'"),
            mock.call("use role old_role"),
        ]
        mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_drop_object_no_special_comment(mock_execute, temp_dir, mock_cursor):
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        mock_cursor(["row"], []),
        mock_cursor(
            [
                {
                    "name": "sample_package_name",
                    "owner": "sample_package_role",
                    "blank": "blank",
                    "comment": "NOT_GENERATED_BY_SNOWCLI",
                }
            ],
            [],
        ),
        mock_cursor(["row"], []),
    ]

    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )
    native_app_manager = NativeAppManager()
    with pytest.raises(
        CouldNotDropObjectError,
        match="Application Package sample_package_name was not created by SnowCLI. Cannot drop the application package.",
    ):
        native_app_manager.drop_object(
            object_name="sample_package_name",
            object_role="sample_package_role",
            object_type="package",
            query_dict={
                "show": "show application packages like",
            },
        )
        expected = [
            mock.call("select current_role()", cursor_class=DictCursor),
            mock.call("use role sample_package_role"),
            mock.call("show application packages like 'sample_package_name'"),
            mock.call("use role old_role"),
        ]
        mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_create_dev_app_noop(mock_execute, temp_dir, mock_cursor):
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role app_role"),
        mock.call("use warehouse app_warehouse"),
        mock.call("show applications like 'myapp'", cursor_class=DictCursor),
        mock.call("alter application myapp set debug_mode = True"),
        mock.call("use role old_role"),
    ]
    # 1:1 with expected calls; these are return values
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        None,
        None,
        mock_cursor(
            [
                {
                    "comment": SPECIAL_COMMENT,
                    "version": LOOSE_FILES_MAGIC_VERSION,
                    "owner": "app_role",
                }
            ],
            [],
        ),
        None,
        None,
    ]

    mock_diff_result = DiffResult()
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    native_app_manager = NativeAppManager()
    assert not mock_diff_result.has_changes()
    native_app_manager._create_dev_app(mock_diff_result)
    assert mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_create_dev_app_recreate(mock_execute, temp_dir, mock_cursor):
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role app_role"),
        mock.call("use warehouse app_warehouse"),
        mock.call("show applications like 'myapp'", cursor_class=DictCursor),
        mock.call("drop application myapp"),
        mock.call(
            f"""
                create application myapp
                    from application package app_pkg
                    using @app_pkg.app_src.stage
                    debug_mode = True
                    comment = {SPECIAL_COMMENT}
                """
        ),
        mock.call("use role old_role"),
    ]
    # 1:1 with expected calls; these are return values
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        None,
        None,
        mock_cursor(
            [
                {
                    "comment": SPECIAL_COMMENT,
                    "version": LOOSE_FILES_MAGIC_VERSION,
                    "owner": "app_role",
                }
            ],
            [],
        ),
        None,
        None,
        None,
    ]

    mock_diff_result = DiffResult(different="setup.sql")
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    native_app_manager = NativeAppManager()
    assert mock_diff_result.has_changes()
    native_app_manager._create_dev_app(mock_diff_result)
    assert mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_create_dev_app_create_new(mock_execute, temp_dir, mock_cursor):
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role app_role"),
        mock.call("use warehouse app_warehouse"),
        mock.call("show applications like 'myapp'", cursor_class=DictCursor),
        mock.call(
            f"""
                create application myapp
                    from application package app_pkg
                    using @app_pkg.app_src.stage
                    debug_mode = True
                    comment = {SPECIAL_COMMENT}
                """
        ),
        mock.call("use role old_role"),
    ]
    # 1:1 with expected calls; these are return values
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        None,
        None,
        mock_cursor([], []),
        None,
        None,
    ]

    mock_diff_result = DiffResult()
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    native_app_manager = NativeAppManager()
    assert not mock_diff_result.has_changes()
    native_app_manager._create_dev_app(mock_diff_result)
    assert mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_create_dev_app_bad_comment(mock_execute, temp_dir, mock_cursor):
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role app_role"),
        mock.call("use warehouse app_warehouse"),
        mock.call("show applications like 'myapp'", cursor_class=DictCursor),
        mock.call("use role old_role"),
    ]
    # 1:1 with expected calls; these are return values
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        None,
        None,
        mock_cursor(
            [
                {
                    "comment": "bad comment",
                    "version": LOOSE_FILES_MAGIC_VERSION,
                    "owner": "app_role",
                }
            ],
            [],
        ),
        None,
    ]

    mock_diff_result = DiffResult()
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    with pytest.raises(ApplicationAlreadyExistsError):
        native_app_manager = NativeAppManager()
        assert not mock_diff_result.has_changes()
        native_app_manager._create_dev_app(mock_diff_result)

    assert mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_create_dev_app_bad_version(mock_execute, temp_dir, mock_cursor):
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role app_role"),
        mock.call("use warehouse app_warehouse"),
        mock.call("show applications like 'myapp'", cursor_class=DictCursor),
        mock.call("use role old_role"),
    ]
    # 1:1 with expected calls; these are return values
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        None,
        None,
        mock_cursor(
            [
                {
                    "comment": SPECIAL_COMMENT,
                    "version": "v1",
                    "owner": "app_role",
                }
            ],
            [],
        ),
        None,
    ]

    mock_diff_result = DiffResult()
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    with pytest.raises(ApplicationAlreadyExistsError):
        native_app_manager = NativeAppManager()
        assert not mock_diff_result.has_changes()
        native_app_manager._create_dev_app(mock_diff_result)

    assert mock_execute.mock_calls == expected


@mock.patch(NATIVEAPP_MANAGER_EXECUTE)
def test_create_dev_app_bad_owner(mock_execute, temp_dir, mock_cursor):
    expected = [
        mock.call("select current_role()", cursor_class=DictCursor),
        mock.call("use role app_role"),
        mock.call("use warehouse app_warehouse"),
        mock.call("show applications like 'myapp'", cursor_class=DictCursor),
        mock.call("use role old_role"),
    ]
    # 1:1 with expected calls; these are return values
    mock_execute.side_effect = [
        mock_cursor([{"CURRENT_ROLE()": "old_role"}], []),
        None,
        None,
        mock_cursor(
            [
                {
                    "comment": SPECIAL_COMMENT,
                    "version": LOOSE_FILES_MAGIC_VERSION,
                    "owner": "accountadmin_or_something",
                }
            ],
            [],
        ),
        None,
    ]

    mock_diff_result = DiffResult()
    current_working_directory = os.getcwd()
    create_named_file(
        file_name="snowflake.yml",
        dir=current_working_directory,
        contents=[mock_snowflake_yml_file],
    )

    with pytest.raises(UnexpectedOwnerError):
        native_app_manager = NativeAppManager()
        assert not mock_diff_result.has_changes()
        native_app_manager._create_dev_app(mock_diff_result)

    assert mock_execute.mock_calls == expected