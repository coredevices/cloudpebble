/* Shows a project's plugin on an emulated watch, in the demo apps that read plugins.
 *
 * Those apps show the user's preferred readings (preferences/complications) first, so the
 * emulator's phone is told the developer's readings are the preferred ones. */
CloudPebble.PluginPreview = (function() {
    // As many slots as the phone app keeps.
    var MAX_READINGS = 5;
    var SOURCE = 'preferences/complications';

    function isSingle(shape) { return shape.indexOf('series.') !== 0; }

    /** Every reading a plugin declares that fits a tile or complication slot, in manifest order. */
    function readings(plugin) {
        var found = [], seen = {};
        ((plugin && plugin.sources) || []).forEach(function(source) {
            (source.items || []).forEach(function(item) {
                Object.keys(source.properties || {}).forEach(function(property) {
                    var shapes = (source.properties[property] || []).filter(isSingle);
                    var key = [source.category, item, property].join('/');
                    // A property that only comes as a series has no single value to show.
                    if (!source.category || !item || seen[key] || !shapes.length) return;
                    seen[key] = true;
                    found.push({key: key, category: source.category, item: item, property: property, shapes: shapes});
                });
            });
        });
        return found;
    }

    function keysOf(list) { return list.map(function(reading) { return reading.key; }); }

    /** The readings to start with: `name` only labels an instance, so everything else goes first. */
    function defaultSelection(available) {
        var values = available.filter(function(reading) { return reading.property !== 'name'; });
        var names = available.filter(function(reading) { return reading.property === 'name'; });
        return keysOf(values.concat(names).slice(0, MAX_READINGS));
    }

    /** A saved choice, less whatever the plugin no longer declares; the defaults if nothing is left. */
    function restoreSelection(available, saved) {
        if (!Array.isArray(saved)) return defaultSelection(available);
        var known = keysOf(available);
        var kept = saved.filter(function(key) { return known.indexOf(key) !== -1; }).slice(0, MAX_READINGS);
        // An empty saved choice was a choice; one emptied by a manifest change wasn't.
        return kept.length || !saved.length ? kept : defaultSelection(available);
    }

    /** preferences/complications in the phone app's wire format: one instance per filled slot. */
    function complicationInstances(selected) {
        function text(value) { return {shortText: {text: value}}; }
        return selected.map(function(reading, position) {
            return {instanceId: String(position), properties: {
                category: text(reading.category),
                item: text(reading.item),
                index: {numericValue: {value: 0}},
                property: text(reading.property)
            }};
        });
    }

    function init(pane) {
        var root = pane.find('.plugin-preview');
        var viewers = window.PLUGIN_PREVIEW_VIEWERS || [];
        var busy = false;
        var storageKey = 'pluginPreviewReadings:' + PROJECT_ID;

        function status(text) { root.find('.plugin-preview-status').text(text); }

        function available() { return readings(CloudPebble.ProjectInfo.plugin); }

        function selected() {
            var chosen = root.find('.plugin-preview-readings input:checked').map(function() { return this.value; }).get();
            return _.filter(available(), function(reading) { return _.contains(chosen, reading.key); });
        }

        function enforceLimit() {
            var boxes = root.find('.plugin-preview-readings input');
            var full = boxes.filter(':checked').length >= MAX_READINGS;
            boxes.not(':checked').prop('disabled', full);
            root.find('.plugin-preview-count').text(interpolate(gettext('%s of %s'), [boxes.filter(':checked').length, MAX_READINGS]));
        }

        function render() {
            var list = available();
            var hasPlugin = !_.isEmpty(CloudPebble.ProjectInfo.plugin);
            root.toggleClass('hide', !hasPlugin);
            if (!hasPlugin) return;
            var saved = null;
            try { saved = JSON.parse(localStorage[storageKey]); } catch (e) { /* nothing saved */ }
            var chosen = restoreSelection(list, saved);
            var holder = root.find('.plugin-preview-readings').empty();
            _.each(list, function(reading) {
                var label = $('<label class="plugin-preview-reading">').appendTo(holder);
                $('<input type="checkbox">').val(reading.key).prop('checked', _.contains(chosen, reading.key)).appendTo(label);
                $('<span class="plugin-preview-reading-name">').text(reading.category + '/' + reading.item + ' · ' + reading.property).appendTo(label);
                $('<span class="plugin-preview-reading-shapes">').text(reading.shapes.join(', ')).appendTo(label);
            });
            if (!list.length) {
                $('<p class="plugin-preview-empty">').text(gettext('This plugin declares no readings yet. Add sources under Plugin in Settings.')).appendTo(holder);
            }
            root.find('.plugin-preview-count').toggleClass('hide', !list.length);
            enforceLimit();

            var show = root.find('.plugin-preview-viewers').empty();
            _.each(viewers, function(viewer) {
                $('<button type="button" class="btn">').text(viewer.name).attr('title', viewer.description)
                    .data('viewer', viewer).appendTo(show);
            });
            var settings = root.find('.plugin-preview-settings').empty();
            if (CloudPebble.ProjectInfo.config_page) {
                $('<button type="button" class="btn">').text(gettext('Plugin settings'))
                    .data('page', {uuid: CloudPebble.ProjectInfo.app_uuid, name: gettext('your plugin')}).appendTo(settings);
            }
            _.each(_.where(viewers, {has_settings: true}), function(viewer) {
                $('<button type="button" class="btn">').text(interpolate(gettext('%s settings'), [viewer.name]))
                    .data('page', {uuid: viewer.uuid, name: viewer.name}).appendTo(settings);
            });
            root.find('.plugin-preview-settings-row').toggleClass('hide', !settings.children().length);
            root.find('.plugin-preview-viewers-row').toggleClass('hide', !viewers.length);
            if (!viewers.length) status(gettext('The preview apps are not installed on this server.'));
            else if (!root.find('.plugin-preview-status').text()) status(gettext('Pick where to show your readings.'));
        }

        /** Resolves to whether this emulator's phone can be told which readings are preferred. */
        function setReadings(pebble, chosen) {
            return pebble.simulator_command(0x0d, '\x02').then(function(plugins) {
                var supported = _.some(plugins, function(plugin) { return _.contains(plugin.sources, SOURCE); });
                if (!supported) return false;
                // No choice puts back the phone's own defaults.
                var instances = chosen.length ? complicationInstances(chosen) : null;
                return pebble.simulator_command(0x0d, '\x01' + JSON.stringify({source: SOURCE, instances: instances}))
                    .then(function() { return true; });
            });
        }

        function preview(viewer) {
            var build = CloudPebble.Compile.GetLastBuild();
            if (!build || build.state != 3 || !build.download) {
                status(!build ? gettext('Run a build first: the preview installs your last build.')
                    : build.state == 1 ? gettext('Wait for the build to finish, then try again.')
                    : gettext('The last build failed. Fix it and build again to preview.'));
                return Promise.resolve();
            }
            var chosen = selected();
            var kind = SharedPebble.isVirtual() ? ConnectionType.Qemu : CloudPebble.Compile.GetEmulatorPlatform();
            status(gettext('Installing your build…'));
            return CloudPebble.Compile.DoInstall({kind: kind, build: build, messages: {
                preparing: gettext('Installing your build…'),
                success: gettext('Your build is installed. Setting up the preview…')
            }}).then(function(pebble) {
                // No pebble: the install offered to reboot the emulator instead.
                if (!pebble) { status(gettext('The install did not finish. Try again once the emulator is back.')); return; }
                return setReadings(pebble, chosen).then(function(supported) {
                    status(interpolate(gettext('Installing %s…'), [viewer.name]));
                    return CloudPebble.Compile.DoInstall({kind: ConnectionType.Qemu, build: {download: viewer.url, sizes: {}}, messages: {
                        preparing: interpolate(gettext('Installing %s…'), [viewer.name]),
                        success: interpolate(gettext('%s is running on the emulator.'), [viewer.name])
                    }}).then(function(installed) {
                        if (!installed) { status(gettext('The install did not finish. Try again once the emulator is back.')); return; }
                        if (!supported) {
                            status(interpolate(gettext('%s is running, but this emulator cannot preset readings. Open its settings to pick your plugin’s readings.'), [viewer.name]));
                        } else if (chosen.length) {
                            status(interpolate(ngettext('%s is showing %s reading from your plugin.', '%s is showing %s readings from your plugin.', chosen.length), [viewer.name, chosen.length]));
                        } else {
                            status(interpolate(gettext('%s is showing the emulator’s built-in readings. Tick some of yours to see them.'), [viewer.name]));
                        }
                    });
                });
            }).catch(function(error) {
                status(error.message || String(error));
            });
        }

        root.on('change', '.plugin-preview-readings input', function() {
            enforceLimit();
            localStorage[storageKey] = JSON.stringify(keysOf(selected()));
        });
        root.on('click', '.plugin-preview-viewers .btn', function() {
            if (busy) return;
            busy = true;
            var buttons = root.find('.plugin-preview-viewers .btn').prop('disabled', true);
            preview($(this).data('viewer')).finally(function() {
                busy = false;
                buttons.prop('disabled', false);
            });
        });
        root.on('click', '.plugin-preview-settings .btn', function() {
            var page = $(this).data('page');
            var url = SharedPebble.getConfigPageURL(page.uuid);
            if (!url) { status(gettext('Start an emulator first: settings pages are served by its phone.')); return; }
            if (!window.open(url, 'emu_config', 'width=375,height=567')) {
                status(gettext('Your browser blocked the settings window. Allow pop-ups for CloudPebble and try again.'));
                return;
            }
            status(interpolate(gettext('Opened the settings page for %s in a new window.'), [page.name]));
        });

        render();
        return {render: render};
    }

    var instance = null;
    return {
        MAX_READINGS: MAX_READINGS,
        readings: readings,
        defaultSelection: defaultSelection,
        restoreSelection: restoreSelection,
        complicationInstances: complicationInstances,
        Init: function(pane) { instance = init(pane); },
        /** The plugin's sources may have changed in Settings since the pane was built. */
        Refresh: function() { if (instance) instance.render(); }
    };
})();
