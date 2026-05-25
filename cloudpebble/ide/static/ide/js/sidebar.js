CloudPebble.Sidebar = (function() {
    var suspended_panes = {};

    var suspend_active_pane = function() {
        var pane_id = $('#main-pane').data('pane-id');
        if (!pane_id) {
            destroy_active_pane();
            $('#pane-parent').append($('<div id="main-pane"></div>'));
            return;
        }
        var pane = $('#main-pane');

        var suspend_function = pane.data('pane-suspend-function');
        if (suspend_function) suspend_function();

        var list_entry = $('#sidebar-pane-' + pane_id);
        if (list_entry) {
            list_entry.removeClass('active');
        }
        suspended_panes[pane_id] = pane;
        pane.detach();
        // Create a new empty one.
        var empty_pane = $('<div id="main-pane"></div>');
        $('#pane-parent').append(empty_pane);
    };

    var destroy_active_pane = function() {
        var pane_id = $('#main-pane').data('pane-id');
        var pane = $('#main-pane');
        if (pane.data('pane-destroy-function')) {
            pane.data('pane-destroy-function')(pane);
        }
        pane.remove();
        var list_entry = $('#sidebar-pane-' + pane_id);
        if (list_entry) {
            list_entry.removeClass('active');
        }
    };

    var restore_suspended_pane = function(id) {
        var pane = suspended_panes[id];
        if (pane) {
            $('#main-pane').remove();
            $('#pane-parent').append(pane);
            delete suspended_panes[id];

            var list_entry = $('#sidebar-pane-' + id);
            if (list_entry) {
                list_entry.addClass('active');
            }

            if (pane.data('pane-restore-function')) {
                pane.data('pane-restore-function')();
            }

            return true;
        }
        return false;
    };

    var set_main_pane = function(pane, options) {
        $('#main-pane').append(pane).data('pane-id', options.id);
        if (options.onRestore) {
            $('#main-pane').data('pane-restore-function', options.onRestore);
        }
        if (options.onDestroy) {
            $('#main-pane').data('pane-destroy-function', options.onDestroy);
        }
        if (options.onSuspend) {
            $('#main-pane').data('pane-suspend-function', options.onSuspend);
        }
    };

    var set_active_menu_entry = function(id) {
        $('#sidebar-pane-' + id).addClass('active');
    };
    
    var get_source_section = function(kind) {
        var id = 'sidebar-sources-' + kind;
        var container = $('#sidebar-sources');
        var section = container.find('#' + id);
        if (!section.length) {
            var header = $('<span class="nav-header">').text(CloudPebble.TargetNames[kind]);
            section = $('<ul class="nav-list">').attr('id', id);
            container.append($('<li>').append([header, section]));
            var add_button = container.find('#new-source-file');
            if (!add_button.length) {
                header.after($('<button class="btn btn-small" id="new-source-file">').click(CloudPebble.Editor.Create).text(gettext('Add new'))).after(" ");
            }
        }
        return section;
    };

    function render_file_link(id, name, on_click) {
        var link = $('<a href="#">').text(name + ' ').click(on_click);
        return $('<li>')
            .attr('id', id)
            .append(link);
    }

    /**
     * Find or create a collapsible folder node within a source section.
     * Supports nested folders (e.g. "assets/images" creates assets/ > images/).
     * @param {jQuery} section - The <ul> source section element
     * @param {string} folder_name - The folder path (e.g. "modules" or "assets/sub")
     * @returns {jQuery} The <ul> inside the deepest folder node
     */
    function get_or_create_folder(section, folder_name) {
        var parts = folder_name.split('/');
        var current_container = section;

        for (var i = 0; i < parts.length; i++) {
            var part = parts[i];
            var folder_id = 'sidebar-folder-' + section.attr('id') + '-' + parts.slice(0, i + 1).join('-');
            var existing = current_container.find('> li.sidebar-folder[data-folder-id="' + folder_id + '"]');

            if (existing.length) {
                current_container = existing.find('> ul.sidebar-folder-contents');
            } else {
                var folder_header = $('<a href="#" class="sidebar-folder-toggle">')
                    .html('<span class="sidebar-folder-arrow">&#9662;</span> ' + part + '/');
                var folder_contents = $('<ul class="nav-list sidebar-folder-contents">');
                var folder_li = $('<li class="sidebar-folder">')
                    .attr('data-folder-id', folder_id)
                    .append(folder_header)
                    .append(folder_contents);

                folder_header.click(function(e) {
                    e.preventDefault();
                    var $this = $(this);
                    var contents = $this.siblings('.sidebar-folder-contents');
                    var arrow = $this.find('.sidebar-folder-arrow');
                    contents.slideToggle(150);
                    if (arrow.html() === '\u25B8') {
                        arrow.html('&#9662;');
                    } else {
                        arrow.html('&#9656;');
                    }
                });

                // Insert folders before non-folder items, sorted alphabetically
                var inserted = false;
                current_container.find('> li.sidebar-folder').each(function() {
                    var existing_name = $(this).find('> a.sidebar-folder-toggle').text().trim();
                    if (part + '/' < existing_name) {
                        $(this).before(folder_li);
                        inserted = true;
                        return false;
                    }
                });
                if (!inserted) {
                    // Insert after last folder but before file items
                    var last_folder = current_container.find('> li.sidebar-folder:last');
                    if (last_folder.length) {
                        last_folder.after(folder_li);
                    } else {
                        current_container.prepend(folder_li);
                    }
                }

                current_container = folder_contents;
            }
        }
        return current_container;
    }

    function create_initial_sections(type) {
        var default_sections_for_project_types = {
            native: ['app', 'pkjs'],
            pebblejs: ['app'],
            simplyjs: ['app'],
            'package': ['app', 'pkjs', 'public'],
            rocky: ['app', 'pkjs', 'common'],
            alloy: ['app', 'embeddedjs', 'pkjs']
        };
        _.each(default_sections_for_project_types[type], get_source_section)
    }

    return {
        SuspendActive: function() {
            suspend_active_pane();
        },
        DestroyActive: function() {
            destroy_active_pane();
        },
        Restore: function(id) {
            var restored = restore_suspended_pane(id);
            if (restored) {
                set_active_menu_entry(id);
            }
            return restored;
        },
        SetActivePane: function(pane, options) {
            var opts = options || {};
            suspend_active_pane();
            set_main_pane(pane, opts);
            set_active_menu_entry(opts.id);
        },
        AddResource: function(resource, on_click) {
            var section = $('#sidebar-resources');
            return render_file_link('sidebar-pane-resource-' + resource.id, resource.file_name, on_click).appendTo(section);
        },
        SetItemName: function(kind, id, new_name) {
            // We need to keep any icons
            var link = $('#sidebar-pane-' + kind + '-' + id + ' a');
            var icons = link.children();
            icons.detach();
            link.text(new_name + ' ').append(icons);
        },
        AddSourceFile: function(file, on_click) {
            var section = get_source_section(file.target);
            var slash_index = file.name.lastIndexOf('/');
            if (slash_index !== -1) {
                var folder_path = file.name.substring(0, slash_index);
                var base_name = file.name.substring(slash_index + 1);
                var folder_ul = get_or_create_folder(section, folder_path);
                return render_file_link("sidebar-pane-source-" + file.id, base_name, on_click).appendTo(folder_ul);
            }
            return render_file_link("sidebar-pane-source-" + file.id, file.name, on_click).appendTo(section);
        },
        Remove: function(id) {
            var item = $('#sidebar-pane-' + id);
            var parent_folder = item.closest('.sidebar-folder-contents');
            item.remove();
            // Clean up empty parent folders
            while (parent_folder.length && parent_folder.hasClass('sidebar-folder-contents')) {
                if (parent_folder.children().length === 0) {
                    var folder_li = parent_folder.closest('.sidebar-folder');
                    parent_folder = folder_li.closest('.sidebar-folder-contents');
                    folder_li.remove();
                } else {
                    break;
                }
            }
        },
        SetIcon: function(pane_id, icon) {
            var a = $('#sidebar-pane-' + pane_id).find('a');
            var i = a.find('i');
            if (i.length === 0) {
                i = $('<i>');
                a.append(i);
            }

            a.find('i').removeClass().addClass('icon-' + icon);
        },
        ShowPending: function(pane_id, text) {
            if (this._pendingTimers && this._pendingTimers[pane_id]) {
                clearInterval(this._pendingTimers[pane_id]);
            }
            this.ClearIcon(pane_id);
            var a = $('#sidebar-pane-' + pane_id).find('a');
            var span = $('<span class="sidebar-pending">').text(text);
            a.append(span);
            var dots = 1;
            this._pendingTimers = this._pendingTimers || {};
            this._pendingTimers[pane_id] = setInterval(function() {
                span.text(text + '.'.repeat(dots));
                dots = (dots % 3) + 1;
            }, 1000);
        },
        HidePending: function(pane_id) {
            if (this._pendingTimers && this._pendingTimers[pane_id]) {
                clearInterval(this._pendingTimers[pane_id]);
                delete this._pendingTimers[pane_id];
            }
            this.ClearIcon(pane_id);
        },
        ClearIcon: function(pane_id) {
            $('#sidebar-pane-' + pane_id).find('a > i, a > .sidebar-pending').remove();
        },
        Init: function() {
            $('#sidebar-pane-new-resource').click(CloudPebble.Resources.Create);
            $('#sidebar-pane-compile > a').click(CloudPebble.Compile.Show);
            $('#sidebar-pane-dependencies > a').click(CloudPebble.Dependencies.Show);
            $('#sidebar-pane-settings > a').click(CloudPebble.Settings.Show);
            $('#sidebar-pane-github > a').click(CloudPebble.GitHub.Show);
            $('#sidebar-pane-timeline > a').click(CloudPebble.Timeline.show);
            if ($('#sidebar-pane-publish').length) {
                $('#sidebar-pane-publish > a').click(CloudPebble.Publish.Show);
            }
            create_initial_sections(CloudPebble.ProjectInfo.type);
        },
        SetPopover: function(pane_id, title, content) {
            $('#sidebar-pane-' + pane_id).find('a').popover('destroy').popover({
                trigger: 'hover',
                title: title,
                content: content,
                html: true,
                animation: false,
                delay: {show: 250},
                container: 'body'
            }).click(function() {
                $(this).popover('hide');
            });
        },
        SetProjectType: function(type) {
            if (type != 'native') {
                $('.native-only').hide();
            }
            if (type != 'package') {
                $('.package-only').hide();
            }
            if (type == 'simplyjs') {
                $('.not-simplyjs').hide();
            }
            if (type == 'pebblejs') {
                $('.not-pebblejs').hide();
            }
            if(type == 'rocky') {
                $('.not-rocky').hide();
            }
            else {
                $('.rocky-only').hide();
            }
            if(type != 'alloy') {
                $('.alloy-only').hide();
            }
        },
        Refresh: function() {
            CloudPebble.Editor.GetUnsavedFiles = function() { return 0; };
            $('#sidebar-sources').empty();
            $('#sidebar-resources').empty();
            create_initial_sections(CloudPebble.ProjectInfo.type);
            Ajax.Get('/ide/project/' + PROJECT_ID + '/info').then(function(data) {
                CloudPebble.ProjectInfo = data;
                var is_alloy = data.type === 'alloy';
                $.each(data.source_files, function(index, value) {
                    if (is_alloy && value.target === 'embeddedjs' && value.is_binary) {
                        if (CloudPebble.Resources && _.isFunction(CloudPebble.Resources.AddAlloyAsset)) {
                            CloudPebble.Resources.AddAlloyAsset(value);
                        }
                        return;
                    }
                    CloudPebble.Editor.Add(value);
                });
                $.each(data.resources, function(index, value) {
                    CloudPebble.Resources.Add(value);
                });
            });
        }
    };
})();