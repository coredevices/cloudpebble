CloudPebble.CompileReboot = {
    shouldShowPrompt: function(error, isVirtual) {
        return isVirtual && !!error && !!error.message && error.message.indexOf('rebooting') !== -1;
    },
    showRebootPrompt: function(errorMessage, kind, build, rebootFn, installFn, rebootModal) {
        rebootModal.find('.reboot-error-message').text(errorMessage);
        rebootModal.find('#reboot-retry-btn').off('click').on('click', function() {
            rebootModal.modal('hide');
            rebootFn().then(function() {
                return installFn(kind, build);
            }).catch(function(err) {
                console.warn('reboot & retry failed:', err);
            });
        });
        rebootModal.modal('show');
    }
};