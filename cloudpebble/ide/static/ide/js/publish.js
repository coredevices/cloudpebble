CloudPebble.Publish = (function() {
    var mPreflightData = null;
    var mScreenshots = {}; // {platform: [{type: 'png'|'gif', blob: Blob, url: dataURL}, ...]}
    var mCapturing = false;
    var mInitialized = false;

    function setEmulatorTime(pebble, timeMs) {
        pebble.set_time_utc(timeMs);
        return Promise.delay(250).then(function() {
            pebble.set_time_utc(timeMs);
            return Promise.delay(250);
        }).then(function() {
            pebble.set_time_utc(timeMs);
            return Promise.delay(1000);
        });
    }

    // Deferred lookup — ConnectionType is defined in pebble.js which may load after this file
    function getConnectionType(platform) {
        var map = {
            'aplite': ConnectionType.QemuAplite,
            'basalt': ConnectionType.QemuBasalt,
            'chalk': ConnectionType.QemuChalk,
            'diorite': ConnectionType.QemuDiorite,
            'emery': ConnectionType.QemuEmery,
            'gabbro': ConnectionType.QemuGabbro,
            'flint': ConnectionType.QemuFlint
        };
        return map[platform];
    }

    function getPlatforms() {
        var platforms = CloudPebble.ProjectInfo.app_platforms;
        if (!platforms) return [];
        return platforms.split(',').filter(function(p) { return p.trim().length > 0; });
    }

    function showError(message) {
        var errorEl = $('#publish-error').empty().removeClass('hide alert-success alert-warning').addClass('alert-error');
        var lowerMsg = (message || '').toLowerCase();

        // Version conflict: show message with deep link to settings
        if (lowerMsg.indexOf('version') !== -1 && lowerMsg.indexOf('already exists') !== -1) {
            var version = CloudPebble.ProjectInfo.app_version_label || '';
            errorEl.append($('<span>').text(interpolate(gettext('Version %s already exists. '), [version])));
            var settingsLink = $('<a href="#">').text(gettext('Update version number.'));
            settingsLink.click(function(e) {
                e.preventDefault();
                CloudPebble.Settings.Show();
            });
            errorEl.append(settingsLink);
        }
        // UUID conflict: show regenerate button
        else if (lowerMsg.indexOf('uuid') !== -1) {
            errorEl.append($('<span>').text(message));
            var regenBtn = $('<button type="button" class="btn btn-small" style="margin-top: 8px; display: block;">')
                .text(gettext('Regenerate UUID'));
            regenBtn.click(function() {
                regenBtn.attr('disabled', 'disabled').text(gettext('Regenerating...'));
                Ajax.Post('/ide/project/' + PROJECT_ID + '/regenerate_uuid')
                .then(function(data) {
                    CloudPebble.ProjectInfo.app_uuid = data.uuid;
                    hideError();
                    preflight();
                }).catch(function(err) {
                    regenBtn.removeAttr('disabled').text(gettext('Regenerate UUID'));
                    showError(interpolate(gettext('Failed to regenerate UUID: %s'), [err.message]));
                });
            });
            errorEl.append(regenBtn);
        }
        // Generic error
        else {
            errorEl.append($('<span>').text(message));
        }
    }

    function hideError() {
        $('#publish-error').addClass('hide');
    }

    function setStatus(text) {
        $('#publish-status-text').text(text);
    }

    function preflight() {
        hideError();
        $('#publish-title').hide();
        $('#publish-status-area').show();
        $('#publish-preflight-progress').show();
        $('#publish-form-area').hide();
        $('#publish-success').addClass('hide');
        setStatus('Checking app store status...');

        SharedPebble.refreshFirebaseToken().then(function() {
        return Ajax.Post('/ide/project/' + PROJECT_ID + '/publish/preflight');
        })
            .then(function(data) {
                mPreflightData = data;
                $('#publish-preflight-progress').hide();
                $('#publish-status-area').hide();

                if (data.is_new_app) {
                    $('#publish-title').text('Publish on Pebble Appstore').show();
                    $('#publish-version-display-group').hide();
                    showNewAppFields(data);
                } else {
                    $('#publish-title').text('Publish Update').show();
                    $('#publish-version-display').text(CloudPebble.ProjectInfo.app_version_label || '');
                    $('#publish-version-display-group').show();
                    hideNewAppFields();
                }

                $('#publish-form-area').show();
                updatePublishButton();
            })
            .catch(function(error) {
                $('#publish-preflight-progress').hide();
                setStatus('Could not check app store status.');
                showError(error.message);
            });
    }

    function showNewAppFields(data) {
        $('#publish-new-app-fields').show();
        $('#publish-name').val(data.app_name || '');
        $('#publish-version').val(data.app_version || '1.0');

        if (data.github_repo) {
            $('#publish-source').val('https://github.com/' + data.github_repo);
        }

        // Category dropdown for watchapps only
        if (!data.is_watchface) {
            var select = $('#publish-category').empty();
            select.append($('<option value="">').text('Select a category...'));
            _.each(data.category_options, function(opt) {
                select.append($('<option>').val(opt.value).text(opt.label));
            });
            $('#publish-category-group').show();
            $('#publish-icon-group').show();
        } else {
            $('#publish-category-group').hide();
            $('#publish-icon-group').hide();
        }

        $('#publish-screenshot-hint').text(
            'Screenshots are optional. Capture from the emulator or upload your own for each platform.'
        );
    }

    function hideNewAppFields() {
        $('#publish-new-app-fields').hide();
        $('#publish-screenshot-hint').text(
            'Optionally capture new screenshots to include with this update.'
        );
    }

    function updatePublishButton() {
        var btn = $('#publish-submit-btn');
        var noBuildMsg = $('#publish-no-build-msg');
        if (!mPreflightData) {
            btn.attr('disabled', 'disabled').hide();
            noBuildMsg.hide();
            return;
        }

        if (!mPreflightData.has_successful_build) {
            btn.attr('disabled', 'disabled').hide();
            noBuildMsg.show();
            return;
        }

        noBuildMsg.hide();
        btn.show();

        if (mPreflightData.is_new_app) {
            btn.text('Publish to App Store');
            var name = $('#publish-name').val().trim();
            var description = $('#publish-description').val().trim();
            var needsCategory = !mPreflightData.is_watchface;
            var category = $('#publish-category').val();

            if (name && description && (!needsCategory || category)) {
                btn.removeAttr('disabled');
            } else {
                btn.attr('disabled', 'disabled');
            }
        } else {
            btn.text('Publish Update');
            btn.removeAttr('disabled');
        }
    }

    function buildScreenshotPlatformUI() {
        var container = $('#publish-screenshot-platforms').empty();
        var platforms = getPlatforms();

        _.each(platforms, function(platform) {
            var section = $('<div class="control-group publish-screenshot-platform">')
                .attr('data-platform', platform);

            section.append($('<label class="control-label">').text(platform.toUpperCase()));

            var controls = $('<div class="controls">');

            var captureBtn = $('<a href="#" class="btn btn-small publish-platform-capture-btn">')
                .text(gettext('Auto-generate'))
                .attr('data-platform', platform)
                .click(function(e) {
                    e.preventDefault();
                    captureSinglePlatform(platform);
                });
            controls.append(captureBtn);

            var uploadBtn = $('<a href="#" class="btn btn-small publish-platform-upload-btn">')
                .text(gettext('Upload'))
                .attr('data-platform', platform);
            var fileInput = $('<input type="file" accept="image/png,image/gif" multiple style="display:none;">')
                .attr('data-platform', platform);
            uploadBtn.click(function(e) {
                e.preventDefault();
                fileInput.click();
            });
            fileInput.change(function() {
                var files = this.files;
                if (!files || !files.length) return;
                if (!mScreenshots[platform]) mScreenshots[platform] = [];
                console.log('[Publish] Upload: ' + files.length + ' file(s) selected for ' + platform);
                for (var i = 0; i < files.length; i++) {
                    (function(file) {
                        var reader = new FileReader();
                        reader.onload = function(ev) {
                            var isGif = file.type === 'image/gif' || file.name.toLowerCase().endsWith('.gif');
                            console.log('[Publish] Upload stored:', file.name, 'type:', file.type, 'size:', file.size, 'as:', isGif ? 'gif' : 'png', 'for:', platform);
                            mScreenshots[platform].push({
                                type: isGif ? 'gif' : 'png',
                                blob: file,
                                url: ev.target.result
                            });
                            updateScreenshotThumbs();
                            updatePublishButton();
                        };
                        reader.readAsDataURL(file);
                    })(files[i]);
                }
                // Reset so same file can be re-selected
                fileInput.val('');
            });
            controls.append(uploadBtn);
            controls.append(fileInput);

            controls.append($('<div class="publish-screenshot-thumbs">'));
            section.append(controls);
            container.append(section);
        });
    }

    function updateScreenshotThumbs() {
        var container = $('#publish-screenshot-platforms');
        var platforms = getPlatforms();

        _.each(platforms, function(platform) {
            var section = container.find('[data-platform="' + platform + '"]');
            var thumbs = section.find('.publish-screenshot-thumbs').empty();
            var items = mScreenshots[platform] || [];

            _.each(items, function(item, index) {
                var thumb = $('<div class="publish-screenshot-thumb" style="display: inline-block; margin-right: 10px; margin-bottom: 10px; text-align: center; vertical-align: top;">');
                thumb.append($('<img>').attr('src', item.url).css({maxWidth: '80px', maxHeight: '80px', display: 'block', margin: '0 auto 4px auto', border: '1px solid #333'}));
                thumb.append($('<span class="muted" style="font-size: 10px; text-transform: uppercase;">').text(item.type));
                var removeBtn = $('<a href="#" class="muted" style="margin-left: 6px; font-weight: bold; text-decoration: none;">').text('×');
                removeBtn.click(function(e) {
                    e.preventDefault();
                    items.splice(index, 1);
                    updateScreenshotThumbs();
                    updatePublishButton();
                });
                thumb.append(removeBtn);
                thumbs.append(thumb);
            });
        });
    }

    function captureScreenshots() {
        if (mCapturing) return;
        mCapturing = true;

        var platforms = getPlatforms();
        var captureBtn = $('#publish-capture-btn').attr('disabled', 'disabled');
        $('.publish-platform-capture-btn').attr('disabled', 'disabled');
        var statusEl = $('#publish-capture-status');
        mScreenshots = {};

        var chain = Promise.resolve();
        _.each(platforms, function(platform) {
            chain = chain.then(function() {
                return captureForPlatform(platform, statusEl);
            });
        });

        chain.then(function() {
            statusEl.text('Done!');
            updateScreenshotThumbs();
            updatePublishButton();
        }).catch(function(error) {
            statusEl.text('Error: ' + error.message);
            showError('Screenshot capture failed: ' + error.message);
        }).finally(function() {
            mCapturing = false;
            captureBtn.removeAttr('disabled');
            $('.publish-platform-capture-btn').removeAttr('disabled');
        });
    }

    function captureSinglePlatform(platform) {
        if (mCapturing) return;
        mCapturing = true;

        var captureBtn = $('.publish-platform-capture-btn[data-platform="' + platform + '"]').attr('disabled', 'disabled');
        $('#publish-capture-btn').attr('disabled', 'disabled');
        var statusEl = $('#publish-capture-status');

        captureForPlatform(platform, statusEl).then(function() {
            statusEl.text('Done with ' + platform + '.');
            updateScreenshotThumbs();
            updatePublishButton();
        }).catch(function(error) {
            statusEl.text('Error: ' + error.message);
            showError('Screenshot capture failed for ' + platform + ': ' + error.message);
        }).finally(function() {
            mCapturing = false;
            captureBtn.removeAttr('disabled');
            $('#publish-capture-btn').removeAttr('disabled');
        });
    }

    function captureForPlatform(platform, statusEl) {
        var connectionType = getConnectionType(platform);
        if (!connectionType) {
            return Promise.reject(new Error('Unknown platform: ' + platform));
        }

        statusEl.text('Booting emulator for ' + platform + '...');

        return SharedPebble.getPebble(connectionType).then(function(pebble) {
            return Ajax.Get('/ide/project/' + PROJECT_ID + '/build/last').then(function(data) {
                if (!data.build || data.build.state !== 3) {
                    throw new Error('No successful build available. Please build first.');
                }
                statusEl.text('Installing app on ' + platform + '...');

                return new Promise(function(resolve, reject) {
                    var installTimeout = setTimeout(function() {
                        pebble.off('status', onStatus);
                        pebble.off('error', onError);
                        reject(new Error('Install timed out on ' + platform));
                    }, 30000);
                    function onStatus(code) {
                        clearTimeout(installTimeout);
                        pebble.off('status', onStatus);
                        pebble.off('error', onError);
                        if (code === 0) {
                            resolve(pebble);
                        } else {
                            reject(new Error('Install failed on ' + platform));
                        }
                    }
                    function onError(e) {
                        clearTimeout(installTimeout);
                        pebble.off('status', onStatus);
                        pebble.off('error', onError);
                        reject(new Error('Install error on ' + platform + ': ' + e));
                    }
                    pebble.on('status', onStatus);
                    pebble.on('error', onError);
                    pebble.install_app(data.build.download);
                });
            });
        }).then(function(pebble) {
            // Wait for app to settle after install
            return Promise.delay(2000).then(function() { return pebble; });
        }).then(function(pebble) {
            // Press the back button every 1s to keep the backlight on during capture
            var backlightInterval = setInterval(function() {
                try {
                    pebble.emu_press_button(Pebble.Button.Back, true);
                    setTimeout(function() {
                        pebble.emu_press_button(Pebble.Button.Back, false);
                    }, 100);
                } catch (e) {
                    // Ignore errors if emulator disconnects
                }
            }, 500);

            function clearBacklight() {
                clearInterval(backlightInterval);
            }

            // Set time to 10:10 for the static screenshot
            var now = new Date();
            var screenshotTime = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 10, 10, 0, 0).getTime();
            statusEl.text('Setting time on ' + platform + '...');
            return setEmulatorTime(pebble, screenshotTime).then(function() {

            statusEl.text('Taking screenshot on ' + platform + '...');

            return new Promise(function(resolve, reject) {
                var timeout = setTimeout(function() {
                    pebble.off('screenshot:complete');
                    pebble.off('screenshot:failed');
                    reject(new Error('Screenshot timed out on ' + platform));
                }, 15000);

                pebble.once('screenshot:complete', function(imgElement) {
                    clearTimeout(timeout);
                    resolve(imgElement);
                });
                pebble.once('screenshot:failed', function(reason) {
                    clearTimeout(timeout);
                    reject(new Error('Screenshot failed: ' + reason));
                });
                pebble.request_screenshot();
            }).then(function(imgElement) {
                // Resize screenshot to exact platform dimensions if needed
                var dims = PLATFORM_DIMENSIONS[platform];
                return resizeScreenshot(imgElement, dims).then(function(result) {
                    if (!mScreenshots[platform]) mScreenshots[platform] = [];
                    mScreenshots[platform].push({
                        type: 'png',
                        blob: result.blob,
                        url: result.url
                    });
                });
            }).then(function() {
                // QEMU 10 / pebble-emery (and other recent boards) silently
                // ignore SetUTC, so we can no longer force the watch to a
                // specific HH:MM:58 to capture a rollover. Instead, wait until
                // a real wall-clock minute boundary will fall inside the
                // recording window. With a 5 s clip and ~2 s of pre-rollover
                // padding, the minute change lands roughly 2 s in.
                //
                // First, re-align the watch clock to wall time. On boards that
                // ignore SetUTC this is a harmless no-op; on boards that honor
                // it, this undoes the 10:10:00 drift from the static
                // screenshot so the host minute boundary actually corresponds
                // to a watch minute boundary.
                statusEl.text('Re-aligning clock on ' + platform + '...');
                return setEmulatorTime(pebble, Date.now()).then(function() {
                    var preRolloverMs = 2000;
                    var nowMs = Date.now();
                    var waitMs = (60000 - (nowMs % 60000)) - preRolloverMs;
                    if (waitMs < 0) waitMs += 60000;
                    statusEl.text('Waiting ' + Math.round(waitMs / 1000) + 's for minute rollover on ' + platform + '...');
                    return Promise.delay(waitMs);
                });
            }).then(function() {
                // Record GIF from VNC canvas
                var canvas = $('#emulator-container canvas')[0];
                if (!canvas) {
                    console.warn('No VNC canvas available for GIF recording on ' + platform);
                    return;
                }

                statusEl.text('Recording GIF on ' + platform + ' (5s)...');
                var dims = PLATFORM_DIMENSIONS[platform];
                var targetW = dims ? dims.width : null;
                var targetH = dims ? dims.height : null;
                return recordGif(canvas, 5000, 10, targetW, targetH).then(function(gifBlob) {
                    var gifUrl = URL.createObjectURL(gifBlob);
                    if (!mScreenshots[platform]) mScreenshots[platform] = [];
                    mScreenshots[platform].push({
                        type: 'gif',
                        blob: gifBlob,
                        url: gifUrl
                    });
                });
            }).then(function() {
                clearBacklight();
                pebble.set_time_utc(Date.now());
                statusEl.text('Done with ' + platform + '.');
                updateScreenshotThumbs();
            }, function(err) {
                clearBacklight();
                pebble.set_time_utc(Date.now());
                throw err;
            });

            }); // end setEmulatorTime chain
        });
    }

    function resizeScreenshot(imgElement, dims) {
        return new Promise(function(resolve) {
            var src = imgElement.src || $(imgElement).attr('src');
            var img = new Image();
            img.onload = function() {
                if (dims && (img.width !== dims.width || img.height !== dims.height)) {
                    console.log('[Publish] Resizing screenshot from', img.width + 'x' + img.height, 'to', dims.width + 'x' + dims.height);
                    var c = document.createElement('canvas');
                    c.width = dims.width;
                    c.height = dims.height;
                    c.getContext('2d').drawImage(img, 0, 0, dims.width, dims.height);
                    c.toBlob(function(blob) {
                        resolve({blob: blob, url: c.toDataURL('image/png')});
                    }, 'image/png');
                } else {
                    dataURLtoBlob(src).then(function(blob) {
                        resolve({blob: blob, url: src});
                    });
                }
            };
            img.src = src;
        });
    }

    // Platform screen dimensions required by the appstore
    var PLATFORM_DIMENSIONS = {
        aplite:  {width: 144, height: 168},
        basalt:  {width: 144, height: 168},
        chalk:   {width: 180, height: 180},
        diorite: {width: 144, height: 168},
        emery:   {width: 200, height: 228},
        flint:   {width: 144, height: 168},
        gabbro:  {width: 260, height: 260}
    };

    function recordGif(canvas, durationMs, fps, targetWidth, targetHeight) {
        var workerUrl = (typeof GIF_WORKER_URL !== 'undefined') ? GIF_WORKER_URL : '/static/ide/external/gif.worker.js';
        var outW = targetWidth || canvas.width;
        var outH = targetHeight || canvas.height;
        var gif = new GIF({
            workers: 2,
            quality: 10,
            width: outW,
            height: outH,
            workerScript: workerUrl
        });
        var interval = 1000 / fps;

        var timer = setInterval(function() {
            var frame = document.createElement('canvas');
            frame.width = outW;
            frame.height = outH;
            frame.getContext('2d').drawImage(canvas, 0, 0, outW, outH);
            gif.addFrame(frame, {delay: interval, copy: true});
        }, interval);

        return new Promise(function(resolve) {
            setTimeout(function() {
                clearInterval(timer);
                gif.on('finished', function(blob) {
                    resolve(blob);
                });
                gif.render();
            }, durationMs);
        });
    }

    function dataURLtoBlob(dataUrl) {
        return new Promise(function(resolve) {
            var parts = dataUrl.split(',');
            var mime = parts[0].match(/:(.*?);/)[1];
            var bstr = atob(parts[1]);
            var n = bstr.length;
            var u8arr = new Uint8Array(n);
            for (var i = 0; i < n; i++) {
                u8arr[i] = bstr.charCodeAt(i);
            }
            resolve(new Blob([u8arr], {type: mime}));
        });
    }

    function submitPublish(e) {
        e.preventDefault();
        if (!mPreflightData) return;

        var btn = $('#publish-submit-btn').attr('disabled', 'disabled');
        var statusEl = $('#publish-submit-status').text('Publishing...');
        hideError();
        $('#publish-success').addClass('hide');

        // Refresh Firebase token before submitting to ensure session token is fresh
        SharedPebble.refreshFirebaseToken().then(function() {

        var formData = new FormData();
        formData.append('is_new_app', mPreflightData.is_new_app ? 'true' : 'false');
        formData.append('app_id', mPreflightData.app_id || '');

        if (mPreflightData.is_new_app) {
            formData.append('name', $('#publish-name').val().trim());
            formData.append('version', $('#publish-version').val().trim());
            formData.append('description', $('#publish-description').val().trim());
            formData.append('source', $('#publish-source').val().trim());
            formData.append('category', $('#publish-category').val() || '');
        }

        formData.append('release_notes', $('#publish-release-notes').val().trim());

        // Add icon files if uploading
        var iconMode = $('input[name="publish-icon-mode"]:checked').val();
        if (iconMode === 'upload') {
            var smallIcon = $('#publish-icon-small')[0];
            var largeIcon = $('#publish-icon-large')[0];
            if (smallIcon && smallIcon.files[0]) formData.append('icon_small', smallIcon.files[0]);
            if (largeIcon && largeIcon.files[0]) formData.append('icon_large', largeIcon.files[0]);
        }

        // Add screenshots — each file gets a unique field name
        var screenshotIndex = 0;
        _.each(mScreenshots, function(items, platform) {
            _.each(items, function(item) {
                var ext = item.type === 'gif' ? '.gif' : '.png';
                var fieldName = 'screenshot_' + platform + '_' + screenshotIndex;
                console.log('[Publish] Attaching screenshot:', fieldName, 'type:', item.type, 'blob size:', item.blob.size);
                formData.append(fieldName, item.blob, fieldName + ext);
                screenshotIndex++;
            });
        });
        console.log('[Publish] Total screenshots:', screenshotIndex, 'platforms:', Object.keys(mScreenshots));

        $.ajax({
            url: '/ide/project/' + PROJECT_ID + '/publish/submit',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            dataType: 'json'
        }).then(function(data) {
            if (data.success) {
                statusEl.text('');
                // Hide form and status area, show only success
                $('#publish-form-area').hide();
                $('#publish-status-area').hide();
                hideError();
                $('#publish-success').removeClass('hide');
                if (data.app_id) {
                    var storeUrl = 'https://apps.repebble.com/' + data.app_id;
                    var dashboardUrl = 'https://appstore-api.repebble.com/dashboard';
                    $('#publish-app-link').attr('href', storeUrl);
                    $('#publish-dashboard-link').attr('href', dashboardUrl);
                    $('#publish-success-store-link, #publish-success-dashboard-link').show();
                } else {
                    $('#publish-success-store-link, #publish-success-dashboard-link').hide();
                }
                // Show screenshot warnings if any
                if (data.screenshot_warnings && data.screenshot_warnings.length) {
                    var warningHtml = '<p class="text-warning"><strong>Screenshot warnings:</strong></p><ul>';
                    _.each(data.screenshot_warnings, function(w) {
                        warningHtml += '<li>' + _.escape(w) + '</li>';
                    });
                    warningHtml += '</ul>';
                    $('#publish-success .well:first').append(warningHtml);
                }
            } else {
                statusEl.text('');
                showError(data.error || 'Publishing failed.');
            }
            btn.removeAttr('disabled');
        }).fail(function(jqXHR) {
            var message = 'Publishing failed.';
            if (jqXHR.responseJSON && jqXHR.responseJSON.error) {
                message = jqXHR.responseJSON.error;
            }
            statusEl.text('');
            showError(message);
            btn.removeAttr('disabled');
        });

        }).catch(function(error) {
            console.error('[Publish] Firebase token refresh failed:', error);
            statusEl.text('');
            showError('Authentication error. Please refresh the page and try again.');
            btn.removeAttr('disabled');
        });
    }

    function initPane() {
        if (mInitialized) return;
        mInitialized = true;

        var pane = $('#publish-pane-template');

        pane.find('#publish-capture-btn').click(function(e) {
            e.preventDefault();
            captureScreenshots();
        });
        pane.find('#publish-form').submit(submitPublish);

        // Update publish button when form fields change
        pane.find('#publish-name, #publish-description, #publish-category').on('input change', updatePublishButton);

        // Toggle icon upload fields
        pane.find('input[name="publish-icon-mode"]').change(function() {
            if ($(this).val() === 'upload') {
                pane.find('#publish-icon-uploads').removeClass('hide');
            } else {
                pane.find('#publish-icon-uploads').addClass('hide');
            }
        });
    }

    return {
        Show: function() {
            CloudPebble.Sidebar.SuspendActive();
            if (CloudPebble.Sidebar.Restore('publish')) {
                // Re-run preflight every time (clears success state, refreshes status)
                preflight();
                return;
            }
            initPane();
            buildScreenshotPlatformUI();
            CloudPebble.Sidebar.SetActivePane($('#publish-pane-template').show(), {id: 'publish'});
            preflight();
        },
        Init: function() {
            // Nothing to initialize at startup
        }
    };
})();
