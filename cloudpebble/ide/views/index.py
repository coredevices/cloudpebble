from django.conf import settings
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe
from ide.models.build import BuildResult
from ide.models.project import Project, TemplateProject
from ide.utils.alloy_templates import list_alloy_templates
from ide.utils.c_templates import list_c_templates
from utils.td_helper import send_td_event

__author__ = 'katharine'


def _with_last_builds(projects):
    """The project list shows each project's last build. Fetch them in one query
    (DISTINCT ON) instead of one per template lookup: the DB is ~120 ms away, so
    the per-project queries made the page take ~10 s for 26 projects."""
    projects = list(projects)
    last = {b.project_id: b for b in BuildResult.objects.filter(project__in=projects)
            .order_by('project_id', '-id').distinct('project_id')}
    for project in projects:
        project.cache_last_build(last.get(project.id))
    return projects


@require_safe
@ensure_csrf_cookie
def index(request, github_account=None, github_project=None):
    if not request.user.is_authenticated:
        return render(request, 'ide/import_login.html', {
            'next_url': request.get_full_path(),
        })
    user = request.user
    my_projects = _with_last_builds(Project.objects.filter(owner=user).order_by('-last_modified'))
    if not user.settings.accepted_terms:
        # Screw it.
        # user_settings = user.settings
        # user_settings.accepted_terms = True
        # user_settings.save()

        return render(request, 'ide/new-owner.html', {
            'my_projects': my_projects
        })
    elif settings.SOCIAL_AUTH_PEBBLE_REQUIRED and user.social_auth.filter(provider='pebble').count() == 0:
        return render(request, 'registration/merge_account.html')
    else:
        send_td_event('cloudpebble_project_list', request=request)
        return render(request, 'ide/index.html', {
            'my_projects': my_projects,
            'sdk_templates': TemplateProject.objects.filter(template_kind=TemplateProject.KIND_TEMPLATE),
            'demo_templates': TemplateProject.objects.filter(template_kind=TemplateProject.KIND_SDK_DEMO),
            'alloy_templates': list_alloy_templates(),
            'c_templates': list_c_templates(),
            'default_template_id': settings.DEFAULT_TEMPLATE,
            'user': user,
        })
