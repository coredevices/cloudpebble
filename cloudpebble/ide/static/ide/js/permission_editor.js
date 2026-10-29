/* Permission declarations stay structured; editing one field preserves imported metadata. */
CloudPebble.PermissionEditor = (function() {
    var catalog = [
        ['Internet', 'Internet', 'Connect to websites. Leave domains empty for all websites.', 'domains'],
        ['LocalNetwork', 'Local network', 'Connect to devices on the local network.'],
        ['Location', 'Location', 'Read the phone’s location.'],
        ['WatchMicrophone', 'Watch microphone', 'Capture audio on supported watches.'],
        ['Notifications', 'Notifications', 'Read notifications. Leave packages empty for all apps.', 'packages'],
        ['Calendar', 'Calendar', 'Read calendar events.'],
        ['Contacts', 'Contacts', 'Read contacts.'],
        ['Timeline', 'Timeline', 'Create timeline pins.'],
        ['ReadWatchSettings', 'Read watch settings', 'Read watch preferences.'],
        ['WriteWatchSettings', 'Change watch settings', 'Update watch preferences.'],
        ['ReadMusic', 'Read music', 'Read the current music information.'],
        ['ControlMusic', 'Control music', 'Control music playback.'],
        ['LaunchApps', 'Launch apps', 'Launch apps on the phone.'],
        ['FindMyPhone', 'Find my phone', 'Make the phone ring.'],
        ['ReadFiles', 'Read files', 'Read files chosen by the user.'],
        ['WriteFiles', 'Write files', 'Change files chosen by the user.'],
        ['LegacyPebbleKit', 'PebbleKit companion', 'Communicate with a PebbleKit Classic companion app.'],
        ['Health', 'Health', 'Read watch health data.']
    ];
    function nameOf(p) { return typeof p === 'string' ? p : p.name; }
    function withList(permission, key, text) {
        var result = typeof permission === 'string' ? {name: permission} : JSON.parse(JSON.stringify(permission));
        result.parameters = result.parameters || {};
        var values = text.split(/[\n,]+/).map(function(s) { return s.trim(); }).filter(Boolean);
        if (values.length) result.parameters[key] = values;
        else delete result.parameters[key];
        if (!Object.keys(result.parameters).length) delete result.parameters;
        return result;
    }
    function mount(container, initial, changed) {
        var permissions = JSON.parse(JSON.stringify(initial || []));
        var list = $('<div class="permission-list">').appendTo(container);
        var add = $('<div class="permission-add">').appendTo(container);
        var select = $('<select aria-label="Permission to add">').appendTo(add);
        $('<option value="">').text(gettext('Choose a permission…')).appendTo(select);
        catalog.forEach(function(item) { $('<option>').val(item[0]).text(gettext(item[1])).appendTo(select); });
        $('<option value="custom">').text(gettext('Custom plugin permission…')).appendTo(select);
        var custom = $('<div class="custom-permission hide">').appendTo(container);
        var customName = $('<input placeholder="Permission name" aria-label="Custom permission name">').appendTo(custom);
        var plugin = $('<input placeholder="Plugin UUID (optional)" aria-label="Permission plugin UUID">').appendTo(custom);
        function notify() { changed(); }
        function render() {
            list.empty();
            if (!permissions.length) $('<p class="help-block">').text(gettext('No permissions requested. Add only what your app needs.')).appendTo(list);
            permissions.forEach(function(permission, index) {
                var name = nameOf(permission);
                var item = catalog.filter(function(c) { return c[0] === name; })[0];
                // A plugin-owned permission may use a built-in name; do not reinterpret its parameters.
                if (permission.plugin) item = null;
                var row = $('<div class="permission-item">').appendTo(list);
                var heading = $('<div class="permission-heading">').appendTo(row);
                $('<span>').text(item ? gettext(item[1]) : name).appendTo(heading);
                $('<button type="button" class="btn permission-remove">').text(gettext('Remove'))
                    .attr('aria-label', gettext('Remove') + ' ' + name).appendTo(heading).click(function() {
                        permissions.splice(index, 1); render(); notify();
                    });
                if (item) $('<p class="help-block">').text(gettext(item[2])).appendTo(row);
                if (permission.plugin) $('<p class="help-block">').text('Plugin: ' + permission.plugin).appendTo(row);
                if (item && item[3]) {
                    var key = item[3];
                    var value = permission.parameters && permission.parameters[key];
                    $('<input type="text">').attr('aria-label', name + ' ' + key)
                        .attr('placeholder', key === 'domains' ? 'api.example.com, example.org' : 'com.example.app')
                        .val(Array.isArray(value) ? value.join(', ') : '')
                        .appendTo(row).on('input', function() {
                            permissions[index] = withList(permissions[index], key, $(this).val());
                            // Let the form record this input before starting its save.
                            setTimeout(notify, 0);
                        });
                }
                if (!item && permission.parameters) {
                    $('<p class="help-block">').text(gettext('Imported parameters are preserved.')).appendTo(row);
                }
            });
        }
        select.change(function() {
            var name = select.val();
            custom.toggleClass('hide', name !== 'custom');
            if (!name || name === 'custom') return;
            if (!permissions.some(function(p) { return !p.plugin && nameOf(p) === name; })) permissions.push(name);
            select.val(''); render(); notify();
        });
        $('<button type="button" class="btn">').text(gettext('Add permission')).appendTo(custom).click(function() {
            var name = customName.val().trim(), uuid = plugin.val().trim();
            if (!name) { customName.focus(); return; }
            if (uuid && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(uuid)) {
                plugin[0].setCustomValidity(gettext('Enter a valid plugin UUID.'));
                plugin[0].reportValidity(); return;
            }
            plugin[0].setCustomValidity('');
            var permission = {name: name};
            if (uuid) permission.plugin = uuid;
            permissions.push(permission); customName.val(''); plugin.val(''); select.val('');
            custom.addClass('hide'); render(); notify();
        });
        render();
        return {value: function() { return permissions; }};
    }
    return {mount: mount, withList: withList};
})();
