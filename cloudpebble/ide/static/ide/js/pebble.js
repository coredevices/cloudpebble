/**
 * Created by katharine on 1/15/15.
 */

var ConnectionType = {
    None: 0,
    Phone: 1,
    Qemu: 2,
    QemuAplite: 6,
    QemuBasalt: 10,
    QemuChalk: 18,
    QemuDiorite: 34,
    QemuEmery: 66,
    QemuGabbro: 130,
    QemuFlint: 258
};

var ConnectionPlatformNames = {
    2: 'aplite',
    6: 'aplite',
    10: 'basalt',
    18: 'chalk',
    34: 'diorite',
    66: 'emery',
    130: 'gabbro',
    258: 'flint'
};

var SharedPebble = new (function() {
    var self = this;
    var mPebble = null;
    var mConnectionType = ConnectionType.None;
    var mEmulator = null;

    _.extend(this, Backbone.Events);

    var LOADING_STATEMENTS = [
        gettext("Reticulating splines…"),
        gettext("Eroding cliffs…"),
        gettext("Charging watches…"),
        gettext("Focusing camera…"),
        gettext("Rendering cats…"),
        gettext("Solving climate change…"),
        gettext("Kickstarting emulator project…"),
        gettext("Herding cats…"),
        gettext("Polishing monocles…"),
        gettext("Drafting master plans…"),
        gettext("Petting unicorns…"),
        gettext("Firing missiles…"),
        gettext("Never giving you up…"),
        gettext("Never letting you down…"),
        gettext("Here comes Tom!")
    ];

    function isRound(kind) {
        return ((kind & ConnectionType.QemuChalk) == ConnectionType.QemuChalk);
    }

    function isGabbro(kind) {
        return ((kind & ConnectionType.QemuGabbro) == ConnectionType.QemuGabbro);
    }

    function isRobert(kind) {
        return ((kind & ConnectionType.QemuEmery) == ConnectionType.QemuEmery);
    }

    function _getEmulator(kind, options) {
        var showProgress = !options || options.showProgress !== false;
        var statementInterval = null;
        var randomStatements = LOADING_STATEMENTS.slice(0);

        if(showProgress) {
            CloudPebble.Prompts.Progress.Show(gettext("Booting emulator…"), gettext("Booting emulator..."));
        }
        statementInterval = setInterval(function() {
            if(statementInterval === null) return;
            if(showProgress) {
                CloudPebble.Prompts.Progress.Update(pickElement(randomStatements));
            }
        }, 2500);
        var emulator_container = $('#emulator-container');
        mEmulator = new QEmu(ConnectionPlatformNames[kind], emulator_container.find('canvas'), {
            up: emulator_container.find('.up'),
            select: emulator_container.find('.select'),
            down: emulator_container.find('.down'),
            back: emulator_container.find('.back'),
        });
        window.emu = mEmulator;
        var hide_emulator = function() {
            $('#sidebar').removeClass('with-emulator with-emulator-gabbro');
            mEmulator = null;
        };
        mEmulator.on('disconnected', hide_emulator);
        $('#sidebar').addClass('with-emulator');
        var canvas_size = URL_BOOT_IMG[ConnectionPlatformNames[kind]].size;
        emulator_container.removeClass('emulator-round emulator-gabbro emulator-robert');
        $('#sidebar').removeClass('with-emulator-gabbro');
        if (isGabbro(kind)) {
            emulator_container.addClass('emulator-gabbro');
            $('#sidebar').addClass('with-emulator-gabbro');
        } else if (isRound(kind)) {
            emulator_container.addClass('emulator-round');
        } else if (isRobert(kind)) {
            emulator_container.addClass('emulator-robert');
        }
        emulator_container.find('canvas').attr('width', canvas_size[0]).attr('height', canvas_size[1]);
        mEmulator.on('disconnected', handleEmulatorDisconnected);
        return mEmulator.connect().catch(function(err) {
            hide_emulator();
            if(showProgress) {
                CloudPebble.Prompts.Progress.Fail();
                CloudPebble.Prompts.Progress.Update(err.message);
            }
            throw err;
        }).then(function() {
            return mEmulator;
        }).finally(function() {
            clearInterval(statementInterval);
        });
    }

    this.getEmulator = function(kind, options) {
        if(mEmulator != null) {
            if((kind & mConnectionType) == kind) {
                return Promise.resolve(mEmulator);
            } else {
                return mEmulator.disconnect(true).then(function() {
                    return _getEmulator(kind, options);
                });
            }
        }
        else {
            return _getEmulator(kind, options);
        }

    };

    function handleEmulatorDisconnected() {
        if(mPebble && (mConnectionType & ConnectionType.Qemu)) {
            mPebble.close();
            mEmulator = null;
        }
    }

    function getPhoneConnectionType() {
        return localStorage['phoneConnectionType'] || 'github';
    }

    function isCloudProxyConnection(kind) {
        if (kind & ConnectionType.Qemu) {
            return false;
        }
        var phoneConnectionType = getPhoneConnectionType();
        return phoneConnectionType === 'clouddev_v2' || phoneConnectionType === 'clouddev';
    }

    function syncFirebaseTokenToSession(idToken) {
        if (!idToken) {
            return Promise.resolve();
        }
        USER_SETTINGS.firebase_token = idToken;
        return Ajax.Post('/accounts/api/firebase-login', {
            id_token: idToken
        }).catch(function(error) {
            console.warn("Failed to sync Firebase token to session:", error);
            return null;
        });
    }

    function refreshFirebaseTokenForCloudProxy(kind) {
        if (!isCloudProxyConnection(kind)) {
            return Promise.resolve();
        }
        if (!window.firebase || !firebase.auth) {
            return Promise.resolve();
        }
        var auth = firebase.auth();
        var user = auth.currentUser;
        if (!user) {
            return Promise.resolve();
        }

        return Promise.resolve(user.getIdToken(false)).then(function(idToken) {
            if (!idToken) {
                return null;
            }
            return Promise.resolve(user.getIdTokenResult(false)).then(function(result) {
                if (result && result.expirationTime) {
                    USER_SETTINGS.firebase_token_exp = Math.floor(new Date(result.expirationTime).getTime() / 1000);
                }
                return syncFirebaseTokenToSession(idToken);
            });
        }).catch(function(error) {
            console.warn("Failed to refresh Firebase token:", error);
            return null;
        });
    }

    this.getPebble = function(kind, options) {
        var showProgress = !options || options.showProgress !== false;
        if(mPebble && mPebble.is_connected()) {
            if(kind === undefined || mConnectionType == kind || (kind == ConnectionType.Qemu && self.isVirtual())) {
                return Promise.resolve(mPebble);
            }
        }

        var watchPromise;

        if(kind & ConnectionType.Qemu) {
            watchPromise = self.getEmulator(kind, options);
        } else {
            watchPromise = Promise.resolve();
        }
        return Promise.join(watchPromise, refreshFirebaseTokenForCloudProxy(kind)).then(function() {
            return new Promise(function(resolve, reject) {
                var did_connect = false;
                mConnectionType = kind;
                if(showProgress) {
                    CloudPebble.Prompts.Progress.Show(gettext("Connecting..."), gettext("Establishing connection..."), function() {
                        if(!did_connect && mPebble) {
                            mPebble.off();
                            mPebble.close();
                            reject(new Error(gettext("Connection interrupted.")));
                        }
                    });
                }
                mPebble = new Pebble(getWebsocketURL(), getToken(), getAuthMode());
                mPebble.on('all', handlePebbleEvent);
                mPebble.on('proxy:authenticating', function() {
                    if(showProgress) {
                        CloudPebble.Prompts.Progress.Update(gettext("Authenticating..."));
                    }
                });
                mPebble.on('proxy:waiting', function() {
                    if(showProgress) {
                        CloudPebble.Prompts.Progress.Update(gettext("Waiting for phone. Make sure the developer connection is enabled."));
                    }
                });
                var connectionError = function(event) {
                    var message = gettext("Connection interrupted");
                    if (isCloudProxyConnection(mConnectionType)) {
                        if (!getToken()) {
                            message = gettext("Missing cloud authentication token. Please sign out and sign back in.");
                        } else if (event && event.code === 4401) {
                            message = gettext("Cloud authentication failed. Please sign out and sign back in.");
                        } else if (event && event.code === 1008) {
                            message = gettext("Cloud proxy rejected the connection.");
                        }
                    }
                    reject(new Error(message));
                };
                mPebble.on('close error', connectionError);
                mPebble.on('open', function() {
                    if(self.isVirtual()) {
                        var date = new Date();
                        if((mConnectionType & ConnectionType.QemuAplite) != ConnectionType.QemuAplite) {
                            // Set pebble timezone
                            mPebble.set_time_utc(date.getTime());
                            console.log("setting pebble clock to utc.");
                        } else {
                            // Set the clock to localtime.
                            mPebble.set_time(date.getTime() - date.getTimezoneOffset() * 60000);
                            console.log("setting pebble clock to localtime.");
                        }
                    }
                    mPebble.enable_app_logs();
                    did_connect = true;
                    mPebble.off(null, connectionError);
                    mPebble.off('proxy:authenticating proxy:waiting');
                    if(showProgress) {
                        CloudPebble.Prompts.Progress.Hide();
                    }
                    resolve(mPebble);
                });
            }).catch(function(error) {
                mPebble.off();
                mPebble = null;
                mEmulator = null;
                if(showProgress) {
                    CloudPebble.Prompts.Progress.Fail();
                    if (mConnectionType & ConnectionType.Qemu) {
                        CloudPebble.Prompts.Progress.Update(interpolate(gettext("Emulator boot failed: %s"), [error.message]));
                    } else {
                        CloudPebble.Prompts.Progress.Update(interpolate(gettext("Phone connection failed: %s"), [error.message]));
                    }
                }
                $('#sidebar').removeClass('with-emulator with-emulator-gabbro');
                throw error;
            });
        });
    };

    this.getPebbleNow = function() {
        return mPebble;
    };

    this.disconnect = function(shutdown) {
        var close_pebble = null;
        var disconnect_emu = null;

        if(mPebble) {
            close_pebble = new Promise(function(resolve) {
                mPebble.disable_app_logs();
                mPebble.close();
                // Wait for a close or error event before disabling events,
                // in order to allow the events to be received by any listeners
                mPebble.on('close error', function() {
                    mPebble.off();
                    mPebble = null;
                    resolve(true);
                });
                mConnectionType = ConnectionType.None;
            });
        }
        if(shutdown === true && mEmulator) {
            disconnect_emu = mEmulator.disconnect();
            mEmulator = null;
        }

        return Promise.join(close_pebble, disconnect_emu).then(function(pebble_closed, emu_disconnected) {
            return pebble_closed || emu_disconnected;
        });
    };

    this.reboot = function() {
        var kind = mConnectionType;
        return this.disconnect(true).then(function() {
            return self.getPebble(kind);
        });
    };

    this.isVirtual = function() {
        return mPebble && !!(mConnectionType & ConnectionType.Qemu);
    };

    this.getPlatformName = function() {
        return ConnectionPlatformNames[mConnectionType];
    };

    function getWebsocketURL() {
        if (mConnectionType & ConnectionType.Qemu) {
            return mEmulator.getWebsocketURL();
        }
        if (isCloudProxyConnection(mConnectionType)) {
            if (typeof CLOUDPEBBLE_PROXY_V2 !== 'undefined' && CLOUDPEBBLE_PROXY_V2) {
                return CLOUDPEBBLE_PROXY_V2;
            }
            return CLOUDPEBBLE_PROXY.replace('/tool', '/tool-v2');
        }
        if (getPhoneConnectionType() === 'devconn') {
            return LIBPEBBLE_PROXY;
        }
        return CLOUDPEBBLE_PROXY;
    }

    function getToken() {
        if (mConnectionType & ConnectionType.Qemu) {
            return mEmulator.getToken();
        }
        if (getPhoneConnectionType() === 'devconn') {
            return USER_SETTINGS.token;
        }
        if (isCloudProxyConnection(mConnectionType)) {
            return USER_SETTINGS.firebase_token || '';
        }
        return USER_SETTINGS.github_dev_connection ? USER_SETTINGS.github_dev_connection.token : '';
    }

    function getAuthMode() {
        if (mConnectionType & ConnectionType.Qemu) {
            return 'v1';
        }
        if (isCloudProxyConnection(mConnectionType)) {
            return 'v2';
        }
        return 'v1';
    }

    function pickElement(elements) {
        if(elements.length == 0) {
            return "…";
        }
        var index = Math.floor(Math.random() * elements.length);
        return elements.splice(index, 1)[0];
    }

    function handlePebbleEvent() {
        var args = Array.prototype.slice.call(arguments, 0);
        var event = args.shift();
        self.trigger.apply(self, [event, mPebble].concat(args));
    }

    /**
     * Refresh the Firebase ID token and sync it to the Django session.
     * Call this before any server-side API that uses the session token
     * (e.g. publish preflight/submit). Returns a Promise.
     *
     * Uses /accounts/api/firebase-refresh-token which updates the session
     * token WITHOUT calling login() (preserves session ID and CSRF token).
     *
     * Waits for onAuthStateChanged to ensure Firebase has restored the
     * user from IndexedDB before checking currentUser.
     */
    this.refreshFirebaseToken = function() {
        if (!window.firebase || !firebase.auth) {
            return Promise.resolve();
        }
        var auth = firebase.auth();

        // Wait for Firebase to restore auth state from IndexedDB
        return new Promise(function(resolve) {
            var unsubscribe = auth.onAuthStateChanged(function(user) {
                unsubscribe();
                resolve(user);
            });
        }).then(function(user) {
            if (!user) {
                return null;
            }
            return Promise.resolve(user.getIdToken(false)).then(function(idToken) {
                if (!idToken) {
                    return null;
                }
                return Promise.resolve(user.getIdTokenResult(false)).then(function(result) {
                    if (result && result.expirationTime) {
                        USER_SETTINGS.firebase_token_exp = Math.floor(new Date(result.expirationTime).getTime() / 1000);
                    }
                    USER_SETTINGS.firebase_token = idToken;
                    return Ajax.Post('/accounts/api/firebase-refresh-token', {
                        id_token: idToken
                    });
                });
            });
        }).catch(function(error) {
            console.warn("Failed to refresh Firebase token:", error);
            return null;
        });
    };
})();
