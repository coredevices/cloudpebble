from django.urls import path, re_path
from django.views.i18n import JavaScriptCatalog

from ide.api import proxy_keen, check_task, get_shortlink, heartbeat
from ide.api.git import github_push, github_pull, set_project_repo, create_project_repo
from ide.api.phone import ping_phone, check_phone, list_phones, update_phone
from ide.api.project import (
    project_info,
    compile_project,
    last_build,
    build_history,
    build_log,
    build_info,
    build_download,
    export_download,
    create_project,
    save_project_settings,
    save_project_dependencies,
    save_published_media,
    save_env_vars,
    delete_project,
    begin_export,
    import_zip,
    import_github,
    do_import_gist,
    get_projects,
    regenerate_uuid,
)
from ide.api.resource import (
    create_resource,
    resource_info,
    delete_resource,
    update_resource,
    show_resource,
    delete_variant,
)
from ide.api.source import (
    create_source_file,
    create_binary_source_file,
    load_source_file,
    download_source_file,
    source_file_is_safe,
    save_source_file,
    delete_source_file,
    rename_source_file,
)
from ide.api.user import (
    transition_accept,
    transition_export,
    transition_delete,
    whats_new,
)
from ide.api.ycm import init_autocomplete
from ide.api.qemu import launch_emulator, generate_phone_token, handle_phone_token
from ide.api.npm import npm_search, npm_info
from ide.api.publish import publish_preflight, publish_submit
from ide.views.index import index
from ide.views.project import (
    view_project,
    github_hook,
    build_status,
    import_gist,
    qemu_config,
    enter_phone_token,
)
from ide.views.run import run_app, run_app_pbw, run_app_heart, run_app_users_me
from ide.views.settings import (
    settings_page,
    start_github_dev_auth,
    remove_github_dev_auth,
    complete_github_dev_auth,
    start_github_repo_sync_install,
    start_github_repo_sync_auth,
    remove_github_repo_sync_auth,
    complete_github_repo_sync_auth,
)

app_name = "ide"
urlpatterns = [
    re_path(r"^$", index, name="index"),
    re_path(
        r"^import/github/(?P<github_account>.+?)/(?P<github_project>.+?)$",
        index,
        name="index",
    ),
    re_path(r"^projects", get_projects, name="get_projects"),
    re_path(r"^project/create", create_project, name="create_project"),
    re_path(r"^project/(?P<project_id>\d+)$", view_project, name="project"),
    re_path(r"^project/(?P<project_id>\d+)/info", project_info, name="project_info"),
    re_path(
        r"^project/(?P<project_id>\d+)/save_settings",
        save_project_settings,
        name="save_project_settings",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/regenerate_uuid",
        regenerate_uuid,
        name="regenerate_uuid",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/save_dependencies",
        save_project_dependencies,
        name="save_project_dependencies",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/save_published_media",
        save_published_media,
        name="save_published_media",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/save_env_vars",
        save_env_vars,
        name="save_env_vars",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/delete", delete_project, name="delete_project"
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/create_source_file",
        create_source_file,
        name="create_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/create_binary_source_file",
        create_binary_source_file,
        name="create_binary_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/source/(?P<file_id>\d+)/load",
        load_source_file,
        name="load_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/source/(?P<file_id>\d+)/save",
        save_source_file,
        name="save_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/source/(?P<file_id>\d+)/rename",
        rename_source_file,
        name="rename_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/source/(?P<file_id>\d+)/is_safe",
        source_file_is_safe,
        name="source_file_is_safe",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/source/(?P<file_id>\d+)/download",
        download_source_file,
        name="download_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/source/(?P<file_id>\d+)/delete",
        delete_source_file,
        name="delete_source_file",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/create_resource",
        create_resource,
        name="create_resource",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/resource/(?P<resource_id>\d+)/info",
        resource_info,
        name="resource_info",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/resource/(?P<resource_id>\d+)/delete",
        delete_resource,
        name="delete_resource",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/resource/(?P<resource_id>\d+)/update",
        update_resource,
        name="update_resource",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/resource/(?P<resource_id>\d+)/(?P<variant>\d+(?:,\d+)*)/get",
        show_resource,
        name="show_resource",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/resource/(?P<resource_id>\d+)/(?P<variant>\d+(?:,\d+)*)/delete",
        delete_variant,
        name="delete_variant",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/build/run",
        compile_project,
        name="compile_project",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/build/last", last_build, name="get_last_build"
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/build/history",
        build_history,
        name="get_build_history",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/analytics", proxy_keen, name="proxy_analytics"
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/build/(?P<build_id>\d+)/log",
        build_log,
        name="get_build_log",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/build/(?P<build_id>\d+)/info",
        build_info,
        name="get_build_info",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/build/(?P<build_id>\d+)/download/(?P<filename>[a-z._]+)",
        build_download,
        name="build_download",
    ),
    re_path(
        r"^export/(?P<export_key>[0-9a-f]{32}/[\w.-]+\.zip)$",
        export_download,
        name="export_download",
    ),
    re_path(r"^project/(?P<project_id>\d+)/export", begin_export, name="begin_export"),
    re_path(
        r"^project/(?P<project_id>\d+)/github/repo$",
        set_project_repo,
        name="set_project_repo",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/github/repo/create$",
        create_project_repo,
        name="create_project_repo",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/github/commit$", github_push, name="github_push"
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/github/pull$", github_pull, name="github_pull"
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/github/push_hook$",
        github_hook,
        name="github_hook",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/status\.png$", build_status, name="build_status"
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/autocomplete/init",
        init_autocomplete,
        name="init_autocomplete",
    ),
    re_path(r"emulator/launch", launch_emulator, name="launch_emulator"),
    re_path(r"emulator/config", qemu_config, name="qemu_config"),
    re_path(
        r"emulator/(?P<emulator_id>[0-9a-f-]{32,36})/mobile_token",
        generate_phone_token,
        name="qemu_mobile_token",
    ),
    re_path(
        r"emulator/token/(?P<token>\d{6})", handle_phone_token, name="qemu_mobile_token"
    ),
    re_path(r"emulator/token/?", enter_phone_token, name="qemu_mobile_token"),
    re_path(r"^task/(?P<task_id>[0-9a-f-]{32,36})", check_task, name="check_task"),
    re_path(r"^shortlink$", get_shortlink, name="get_shortlink"),
    re_path(r"^settings$", settings_page, name="settings"),
    re_path(r"^settings/github/start$", start_github_dev_auth, name="start_github_dev_auth"),
    re_path(
        r"^settings/github/callback$", complete_github_dev_auth, name="complete_github_dev_auth"
    ),
    re_path(r"^settings/github/unlink$", remove_github_dev_auth, name="remove_github_dev_auth"),
    re_path(
        r"^settings/github-sync/install$",
        start_github_repo_sync_install,
        name="start_github_repo_sync_install",
    ),
    re_path(
        r"^settings/github-sync/start$",
        start_github_repo_sync_auth,
        name="start_github_repo_sync_auth",
    ),
    re_path(
        r"^settings/github-sync/callback$",
        complete_github_repo_sync_auth,
        name="complete_github_repo_sync_auth",
    ),
    re_path(
        r"^settings/github-sync/unlink$",
        remove_github_repo_sync_auth,
        name="remove_github_repo_sync_auth",
    ),
    re_path(r"^import/zip", import_zip, name="import_zip"),
    re_path(r"^import/github", import_github, name="import_github"),
    re_path(r"^import/gist", do_import_gist, name="import_gist"),
    re_path(r"^transition/accept", transition_accept, name="transition_accept"),
    re_path(r"^transition/export", transition_export, name="transition_export"),
    re_path(r"^transition/delete", transition_delete, name="transition_delete"),
    re_path(
        r"^project/(?P<project_id>\d+)/publish/preflight$",
        publish_preflight,
        name="publish_preflight",
    ),
    re_path(
        r"^project/(?P<project_id>\d+)/publish/submit$",
        publish_submit,
        name="publish_submit",
    ),
    re_path(r"^packages/search", npm_search, name="package_search"),
    re_path(r"^packages/info", npm_info, name="package_info"),
    re_path(r"^ping_phone$", ping_phone),
    re_path(r"^check_phone/(?P<request_id>[0-9a-f-]+)$", check_phone),
    re_path(r"^update_phone$", update_phone),
    re_path(r"^list_phones$", list_phones),
    re_path(r"^whats_new", whats_new, name="whats_new"),
    re_path(r"^gist/(?P<gist_id>[0-9a-f]+)$", import_gist),
    re_path(r"^heartbeat$", heartbeat),
    re_path(r"^run/(?P<app_id>[a-f0-9]{24})$", run_app, name="run_app"),
    re_path(r"^run/(?P<app_id>[a-f0-9]{24})/pbw$", run_app_pbw, name="run_app_pbw"),
    re_path(r"^run/(?P<app_id>[a-f0-9]{24})/heart$", run_app_heart, name="run_app_heart"),
    re_path(r"^run/(?P<app_id>[a-f0-9]{24})/users-me$", run_app_users_me, name="run_app_users_me"),
    re_path(r"^jsi18n/$", JavaScriptCatalog.as_view(), name="jsi18n"),
]
