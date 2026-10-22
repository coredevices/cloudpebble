import datetime
import time
import json
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_safe
from django.utils.translation import gettext as _
from ide.models.project import Project
from ide.models.files import SourceFile
from utils.agent_token import allow_agent_token
from utils.td_helper import send_td_event
from utils.jsonview import json_view, BadRequest

__author__ = "katharine"


@allow_agent_token
@require_POST
@login_required
@json_view
def create_source_file(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    target = request.POST.get("target", "app")
    if target == "embeddedjs" and project.app_platforms:
        unsupported = set(project.app_platform_list) - {"emery", "gabbro"}
        if unsupported:
            raise BadRequest(
                _(
                    "Embedded JS files require only Emery/Gabbro platforms. "
                    "Please remove unsupported platforms (%s) in project settings first."
                )
                % ", ".join(sorted(unsupported))
            )
    try:
        f = SourceFile.objects.create(
            project=project, file_name=request.POST["name"], target=target
        )
        f.save_text(request.POST.get("content", ""))

    except IntegrityError as e:
        raise BadRequest(str(e))

    send_td_event(
        "cloudpebble_create_file",
        data={
            "data": {
                "filename": request.POST["name"],
                "kind": "source",
                "target": f.target,
            }
        },
        request=request,
        project=project,
    )

    return {
        "file": {
            "id": f.id,
            "name": f.file_name,
            "target": f.target,
            "file_path": f.project_path,
        }
    }


@allow_agent_token
@require_safe
@csrf_protect
@login_required
@json_view
def load_source_file(request, project_id, file_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_file = get_object_or_404(SourceFile, pk=file_id, project=project)

    content = source_file.get_contents()
    read_only = not source_file.is_editable_text
    if read_only:
        content = _("This is a binary file and cannot be edited in CloudPebble.")
    elif isinstance(content, bytes):
        content = content.decode("utf-8")

    try:
        folded_lines = json.loads(source_file.folded_lines)
    except ValueError:
        folded_lines = []

    send_td_event(
        "cloudpebble_open_file",
        data={"data": {"filename": source_file.file_name, "kind": "source"}},
        request=request,
        project=project,
    )

    return {
        "source": content,
        "read_only": read_only,
        "modified": time.mktime(source_file.last_modified.utctimetuple()),
        "folded_lines": folded_lines,
    }


@require_safe
@csrf_protect
@login_required
@json_view
def source_file_is_safe(request, project_id, file_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_file = get_object_or_404(SourceFile, pk=file_id, project=project)
    client_modified = datetime.datetime.fromtimestamp(int(request.GET["modified"]))
    server_modified = source_file.last_modified.replace(tzinfo=None, microsecond=0)
    is_safe = client_modified >= server_modified
    return {"safe": is_safe}


@require_POST
@login_required
@json_view
def rename_source_file(request, project_id, file_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_file = get_object_or_404(SourceFile, pk=file_id, project=project)
    old_filename = source_file.file_name

    if source_file.file_name != request.POST["old_name"]:
        send_td_event(
            "cloudpebble_rename_abort_unsafe",
            data={"data": {"filename": source_file.file_name, "kind": "source"}},
            request=request,
            project=project,
        )
        raise BadRequest(_("Could not rename, file has been renamed already."))
    if source_file.was_modified_since(int(request.POST["modified"])):
        send_td_event(
            "cloudpebble_rename_abort_unsafe",
            data={
                "data": {
                    "filename": source_file.file_name,
                    "kind": "source",
                    "modified": time.mktime(source_file.last_modified.utctimetuple()),
                }
            },
            request=request,
            project=project,
        )
        raise BadRequest(_("Could not rename, file has been modified since last save."))
    source_file.file_name = request.POST["new_name"]
    source_file.save()

    send_td_event(
        "cloudpebble_rename_file",
        data={
            "data": {
                "old_filename": old_filename,
                "new_filename": source_file.file_name,
                "kind": "source",
            }
        },
        request=request,
        project=project,
    )
    return {
        "modified": time.mktime(source_file.last_modified.utctimetuple()),
        "file_path": source_file.project_path,
    }


@allow_agent_token
@require_POST
@login_required
@json_view
def save_source_file(request, project_id, file_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_file = get_object_or_404(SourceFile, pk=file_id, project=project)
    if not source_file.is_editable_text:
        raise BadRequest(_("Cannot save binary source files from the editor."))
    if source_file.was_modified_since(int(request.POST["modified"])):
        send_td_event(
            "cloudpebble_save_abort_unsafe",
            data={"data": {"filename": source_file.file_name, "kind": "source"}},
            request=request,
            project=project,
        )
        raise Exception(_("Could not save: file has been modified since last save."))
    source_file.save_text(request.POST["content"])
    source_file.save_lines(folded_lines=request.POST["folded_lines"])

    send_td_event(
        "cloudpebble_save_file",
        data={"data": {"filename": source_file.file_name, "kind": "source"}},
        request=request,
        project=project,
    )

    return {"modified": time.mktime(source_file.last_modified.utctimetuple())}


@allow_agent_token
@require_POST
@login_required
@json_view
def create_binary_source_file(request, project_id):
    """Create a source file from a binary file upload (e.g. .png, .ttf, .pdc assets for alloy embeddedjs)."""
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    target = request.POST.get("target", "embeddedjs")
    file_name = request.POST.get("name", "")

    if not file_name:
        raise BadRequest(_("You must specify a filename."))

    if target == "embeddedjs" and project.app_platforms:
        unsupported = set(project.app_platform_list) - {"emery", "gabbro"}
        if unsupported:
            raise BadRequest(
                _(
                    "Embedded JS files require only Emery/Gabbro platforms. "
                    "Please remove unsupported platforms (%s) in project settings first."
                )
                % ", ".join(sorted(unsupported))
            )

    posted_file = request.FILES.get("file", None)
    if posted_file is None:
        raise BadRequest(_("No file was uploaded."))

    if posted_file.size > 5 * 1024 * 1024:
        raise BadRequest(_("File is too large (max 5MB)."))

    try:
        f = SourceFile.objects.create(
            project=project, file_name=file_name, target=target
        )
        # Save as binary data
        f.save_string(posted_file.read())
    except IntegrityError as e:
        raise BadRequest(str(e))

    send_td_event(
        "cloudpebble_create_file",
        data={
            "data": {
                "filename": file_name,
                "kind": "source",
                "target": f.target,
                "binary": True,
            }
        },
        request=request,
        project=project,
    )

    return {
        "file": {
            "id": f.id,
            "name": f.file_name,
            "target": f.target,
            "file_path": f.project_path,
            "is_binary": f.is_binary_source,
            "is_editable": f.is_editable_text,
            "lastModified": time.mktime(f.last_modified.utctimetuple()),
        }
    }


@allow_agent_token
@require_safe
@csrf_protect
@login_required
def download_source_file(request, project_id, file_id):
    """Serve a source file's raw binary content (for asset preview/download)."""
    from django.http import HttpResponse
    import mimetypes

    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_file = get_object_or_404(SourceFile, pk=file_id, project=project)
    content = source_file.get_contents()
    if isinstance(content, str):
        content = content.encode("utf-8")
    content_type, _ = mimetypes.guess_type(source_file.file_name)
    if not content_type:
        content_type = "application/octet-stream"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        'inline; filename="%s"' % source_file.file_name.split("/")[-1]
    )
    return response


@allow_agent_token
@require_POST
@login_required
@json_view
def delete_source_file(request, project_id, file_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_file = get_object_or_404(SourceFile, pk=file_id, project=project)

    source_file.delete()

    send_td_event(
        "cloudpebble_delete_file",
        data={"data": {"filename": source_file.file_name, "kind": "source"}},
        request=request,
        project=project,
    )
