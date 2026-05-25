CloudPebble.GitHub = (function() {
    var github_template = null;

    var create_repo = function(new_repo) {
        var prompt = $('#github-new-repo-prompt').modal();
        var repo_name = new_repo.match(/^(?:https?:\/\/|git@|git:\/\/)?(?:www\.)?github\.com[\/:]([\w.-]+)\/([\w.-]+?)(?:\.git|\/|$)/)[2];
        prompt.find('#github-new-repo').val(repo_name);
        prompt.find('.alert').removeClass('alert-error').addClass('alert-warning').text(gettext("That repo does not exist. Would you like to create it?"));
    };

    var show_github_pane = function() {
        if(!USER_SETTINGS.github_repo_sync) {
            window.location.href = '/ide/settings';
            return;
        }
        CloudPebble.Sidebar.SuspendActive();
        if(CloudPebble.Sidebar.Restore("github")) {
            return;
        }
        var pane = github_template.clone();
        var show_alert = function(type, message) {
            pane.find('.alert').removeClass('hide alert-error alert-warning alert-info alert-success').addClass('alert-' + type).text(message);
        };
        var clear_alert = function() {
            pane.find('.alert').addClass('hide');
        };
        var disable_all = function() {
            pane.find('input, button').attr('disabled', 'disabled');
        };
        var enable_all = function() {
            pane.find('input, button').removeAttr('disabled');
        };
        var disable_needy = function() {
            pane.find('.github-actions').find('input, button').attr('disabled', 'disabled');
        };
        var enable_needy = function() {
            pane.find('.github-actions').find('input, button').removeAttr('disabled');
        };
        var update_pull_mode_ui = function() {
            var auto_pull = pane.find('#github-repo-hook').val() == '1';
            var force_checkbox = pane.find('#github-repo-hook-force');
            var help_text = pane.find('#github-repo-hook-help');
            if (auto_pull) {
                force_checkbox.removeAttr('disabled');
                if (force_checkbox.is(':checked')) {
                    help_text.html(gettext("Auto-pull will <em>wipe and re-import</em> all files from GitHub every time you push. This is slower but more thorough than the default delta sync."));
                } else {
                    help_text.html(gettext("Auto-pull will sync only the <em>changed files</em> from GitHub every time you push. This is fast but check the box above for a full re-import if you encounter issues."));
                }
            } else {
                force_checkbox.attr('disabled', 'disabled');
                help_text.html(gettext("You will need to pull from GitHub manually using the button below. Auto-pull is disabled."));
            }
        };

        pane.find('#github-repo-form').submit(function(e) {
            e.preventDefault();
            clear_alert();
            var new_repo = pane.find('#github-repo').val();
            var repo_branch = pane.find('#github-branch').val();
            var auto_pull = pane.find('#github-repo-hook').val() == '1';
            var auto_build = pane.find('#github-repo-build').val() == '1';
            var hook_force = pane.find('#github-repo-hook-force').is(':checked');

            if(repo_branch == null || repo_branch.length == 0) {
                repo_branch = "master";
            }

            if((new_repo === CloudPebble.ProjectInfo.github.repo || !new_repo && !CloudPebble.ProjectInfo.github.repo) &&
                (repo_branch === CloudPebble.ProjectInfo.github.branch || !repo_branch && !CloudPebble.ProjectInfo.github.branch) &&
                auto_pull === CloudPebble.ProjectInfo.github.auto_pull && auto_build === CloudPebble.ProjectInfo.github.auto_build && hook_force === CloudPebble.ProjectInfo.github.hook_force) {
                show_alert('success', "Updated repo (nothing changed).");
                return;
            }
            disable_all();
            var data = {
                repo: new_repo,
                auto_pull: auto_pull ? '1' : '0',
                auto_build: auto_build ? '1' : '0',
                hook_force: hook_force ? '1' : '0',
                branch: repo_branch
            };
            Ajax.Post('/ide/project/' + PROJECT_ID + '/github/repo', data).then(function(data) {
                enable_all();
                if(data.updated) {
                    show_alert('success', gettext("Updated repo."));
                    CloudPebble.ProjectInfo.github.repo = new_repo;
                    CloudPebble.ProjectInfo.github.branch = repo_branch;
                    CloudPebble.ProjectInfo.github.auto_pull = auto_pull;
                    CloudPebble.ProjectInfo.github.auto_build = auto_build;
                    CloudPebble.ProjectInfo.github.hook_force = hook_force;
                    return;
                }
                if(!data.exists) {
                    disable_needy();
                    create_repo(new_repo);
                    return;
                }
                if(!data.access) {
                    throw new Error(gettext("You don't have access to that repository."));
                }
            }).catch(function(error) {
                enable_all();
                disable_needy();
                show_alert('error', error.message);
            });
        });

        pane.find('#github-repo').on('input', function() {
            var new_repo = $(this).val();
            if(new_repo !== CloudPebble.ProjectInfo.github.repo || !new_repo) {
                disable_needy();
            } else {
                disable_needy();
            }
        });
        if(CloudPebble.ProjectInfo.github.repo) {
            pane.find('#github-repo').val(CloudPebble.ProjectInfo.github.repo);
            enable_needy();
        }
        if(CloudPebble.ProjectInfo.github.branch) {
            pane.find('#github-branch').val(CloudPebble.ProjectInfo.github.branch);
        }
        pane.find('#github-repo-hook').val(CloudPebble.ProjectInfo.github.auto_pull ? '1' : '0');
        pane.find('#github-repo-build').val(CloudPebble.ProjectInfo.github.auto_build ? '1' : '0');
        pane.find('#github-repo-hook-force').prop('checked', CloudPebble.ProjectInfo.github.hook_force);
        pane.find('#github-repo-hook').on('change', update_pull_mode_ui);
        pane.find('#github-repo-hook-force').on('change', update_pull_mode_ui);
        update_pull_mode_ui();
        var lastSync = CloudPebble.ProjectInfo.github.last_sync;
        if(lastSync) {
            pane.find('#github-last-sync').text(interpolate(gettext('Last synced: %s'), [lastSync]));
        }

        var prompt = $('#github-new-repo-prompt');
        prompt.find('form').submit(function(e) {
            e.preventDefault();
            var new_repo = $('#github-new-repo').val();
            if(new_repo.replace(/\s/g, '') === '') {
                prompt.find('.alert').removeClass('alert-warning').addClass('alert-error').text(gettext("You must provide a repo URL."));
            }
            var description = $('#github-repo-description').val();
            prompt.find('input, button').prop('disabled', true);
            Ajax.Post('/ide/project/' + PROJECT_ID + '/github/repo/create', {repo: new_repo, description: description}).then(function(data) {
                pane.find('#github-repo').val(data.repo);
                CloudPebble.ProjectInfo.github.repo = new_repo;
                pane.find('#github-branch').val(data.branch);
                CloudPebble.ProjectInfo.github.branch = data.branch;
                prompt.modal('hide');
                enable_all();
            }).catch(function(error) {
                prompt.find('.alert').removeClass('alert-warning').addClass('alert-error').text(error);
            }).finally(function() {
                prompt.find('input, button').prop('disabled', false);
            });
        });
        pane.find('#github-push-btn').click(function() {
            $('#github-commit-prompt').modal().find('.alert, .progress').addClass('hide');
            $('#github-commit-prompt').find('input[type=text], textarea').val('');
            $('#github-commit-prompt').focus();
        });

        pane.find('#github-pull-btn').click(function() {
            var prompt = $('#github-pull-prompt').modal();
            prompt.find(".running").addClass('hide');
            prompt.find(".close, .dire-warning, .modal-footer").removeClass("hide");
            prompt.find('#github-pull-force').prop('checked', false);
            prompt.find('#github-pull-force-warning').addClass('hide');
        });

        $(document).on('change', '#github-pull-force', function() {
            $('#github-pull-force-warning').toggleClass('hide', !$(this).is(':checked'));
        });

        var poll_commit_status = function(task_id) {
            return Ajax.PollTask(task_id).finally(function() {
                $('#github-commit-prompt').find('.progress').addClass('hide');
                $('#github-commit-prompt').modal('hide');
            }).then(function(result) {
                show_alert('success', result ? "Made new commit." : "Nothing to commit.");
                return result;
            }).catch(function(error) {
                show_alert('error', 'Error: ' + error.message);
                throw error;
            });
        };

        var poll_pull_status = function(task_id) {
            return Ajax.PollTask(task_id).then(function(result) {
                if(result) {
                    show_alert('success', gettext("Pulled successfully."));
                } else {
                    var lastSync = CloudPebble.ProjectInfo.github.last_sync;
                    if(lastSync) {
                        show_alert('success', interpolate(gettext("Already up to date (last synced %s)."), [lastSync]));
                    } else {
                        show_alert('success', gettext("Pull completed: Nothing to pull."));
                    }
                }
            });
        };

        $('#github-commit-prompt form').submit(function(e) {
            e.preventDefault();
            var commit_summary = $('#github-commit-summary').val();
            var commit_description = $('#github-commit-description').val();
            if(commit_summary.replace(/\s/g, '') === '') {
                $('#github-commit-prompt form').find('.alert').addClass('alert-error').removeClass('hide').text(gettext("You must provide a commit summary."));
                return;
            }
            var commit_message = commit_summary;
            if(commit_description !== '') {
                commit_message += "\n\n" + commit_description.replace("\r\n", "\n");
            }
            disable_all();
            $('#github-commit-prompt').find('input, textarea, button').attr('disabled', 'disabled');
            $('#github-commit-prompt').find('.progress').removeClass('hide');
            Ajax.Post('/ide/project/' + PROJECT_ID + '/github/commit', {commit_message: commit_message}).then(function(data) {
                return poll_commit_status(data.task_id);
            }).catch(function(error) {
                $('#github-commit-prompt form').find('.alert').addClass('alert-error').removeClass('hide').text(error);
            }).finally(function() {
                enable_all();
                $('#github-commit-prompt').find('input, textarea, button').removeAttr('disabled');
            });
            ga('send', 'event', 'github', 'push');
        });

        $('#github-pull-prompt-confirm').click(function() {
            disable_all();
            var prompt = $('#github-pull-prompt');
            prompt.modal('hide');
            var forcePull = prompt.find('#github-pull-force').is(':checked') ? '1' : '0';
            Ajax.Post('/ide/project/' + PROJECT_ID + '/github/pull', {force: forcePull}).then(function(data) {
                return poll_pull_status(data.task_id);
            }).catch(function(error) {
                show_alert('error', interpolate(gettext("Pull failed: %s"), [error.message]));
            }).finally(function() {
                enable_all();
            });
            ga('send', 'event', 'github', 'pull');
        });

        CloudPebble.Sidebar.SetActivePane(pane, {id: 'github'});
    };

    return {
        Init: function() {
            github_template = $('#github-template').remove().removeClass('hide');
            if(!USER_SETTINGS.github_repo_sync) {
                CloudPebble.Sidebar.SetPopover('github', '', gettext('GitHub Repo Sync can be enabled in your user settings by linking a GitHub account.'));
            }
        },
        Show: function() {
            show_github_pane();
        },
        OnPullStart: function() {
            $('#github-push-btn, #github-pull-btn').attr('disabled', 'disabled');
            $('#github-last-sync').text(gettext('Pulling from GitHub...'));
        },
        OnPullComplete: function(data) {
            $('#github-push-btn, #github-pull-btn').removeAttr('disabled');
            var lastSync = data && data.github_last_sync ? data.github_last_sync : '';
            $('#github-last-sync').text(lastSync ? interpolate(gettext('Last synced: %s'), [lastSync]) : gettext('Pull completed.'));
            CloudPebble.Sidebar.Refresh();
        },
        OnPullFailed: function() {
            $('#github-push-btn, #github-pull-btn').removeAttr('disabled');
            $('#github-last-sync').text(gettext('Pull failed.'));
        }
    };
})();
