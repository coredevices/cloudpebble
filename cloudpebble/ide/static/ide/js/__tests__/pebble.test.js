import { describe, it, expect, vi, beforeEach } from 'vitest';

function createSharedPebble() {
    const ConnectionType = {
        None: 0, Phone: 1, Qemu: 2,
        QemuAplite: 6, QemuBasalt: 10, QemuChalk: 18,
        QemuDiorite: 34, QemuEmery: 66, QemuGabbro: 130, QemuFlint: 258
    };

    let mConnectionType = ConnectionType.None;
    let disconnectFn = () => Promise.resolve(false);
    let getPebbleFn = () => Promise.resolve('mock-pebble');

    function isVirtual() {
        return !!(mConnectionType & ConnectionType.Qemu);
    }

    function reboot() {
        var kind = mConnectionType;
        return disconnectFn(true).then(function() {
            return getPebbleFn(kind);
        });
    }

    return {
        ConnectionType,
        reboot,
        isVirtual,
        get mConnectionType() { return mConnectionType; },
        set mConnectionType(v) { mConnectionType = v; },
        setDisconnect(fn) { disconnectFn = fn; },
        setGetPebble(fn) { getPebbleFn = fn; },
        disconnectSpy: null,
        getPebbleSpy: null,
    };
}

describe('SharedPebble.reboot', () => {
    let pebble;

    beforeEach(() => {
        pebble = createSharedPebble();
    });

    it('calls disconnect(true) then getPebble', async () => {
        const disconnectCalls = [];
        pebble.setDisconnect((shutdown) => {
            disconnectCalls.push(shutdown);
            return Promise.resolve(false);
        });
        pebble.setGetPebble(() => Promise.resolve('pebble'));

        await pebble.reboot();

        expect(disconnectCalls).toEqual([true]);
    });

    it('calls getPebble after disconnect resolves', async () => {
        const order = [];
        pebble.setDisconnect(() => {
            order.push('disconnect');
            return Promise.resolve(false);
        });
        pebble.setGetPebble(() => {
            order.push('getPebble');
            return Promise.resolve('pebble');
        });

        await pebble.reboot();

        expect(order).toEqual(['disconnect', 'getPebble']);
    });

    it('passes the connection type that was active before disconnect', async () => {
        pebble.mConnectionType = pebble.ConnectionType.QemuBasalt;
        const getPebbleCalls = [];
        pebble.setDisconnect(() => Promise.resolve(false));
        pebble.setGetPebble((kind) => {
            getPebbleCalls.push(kind);
            return Promise.resolve('pebble');
        });

        await pebble.reboot();

        expect(getPebbleCalls).toEqual([pebble.ConnectionType.QemuBasalt]);
    });

    it('re-throws if disconnect rejects', async () => {
        pebble.setDisconnect(() => Promise.reject(new Error('disconnect failed')));
        pebble.setGetPebble(() => Promise.resolve('pebble'));

        await expect(pebble.reboot()).rejects.toThrow('disconnect failed');
    });

    it('re-throws if getPebble rejects', async () => {
        pebble.setDisconnect(() => Promise.resolve(false));
        pebble.setGetPebble(() => Promise.reject(new Error('launch failed')));

        await expect(pebble.reboot()).rejects.toThrow('launch failed');
    });
});

describe('SharedPebble.isVirtual', () => {
    let pebble;

    beforeEach(() => {
        pebble = createSharedPebble();
    });

    it('returns true when connection type is QemuBasalt', () => {
        pebble.mConnectionType = pebble.ConnectionType.QemuBasalt;
        expect(pebble.isVirtual()).toBe(true);
    });

    it('returns true when connection type is QemuChalk', () => {
        pebble.mConnectionType = pebble.ConnectionType.QemuChalk;
        expect(pebble.isVirtual()).toBe(true);
    });

    it('returns false for Phone connection type', () => {
        pebble.mConnectionType = pebble.ConnectionType.Phone;
        expect(pebble.isVirtual()).toBe(false);
    });

    it('returns false for None connection type', () => {
        pebble.mConnectionType = pebble.ConnectionType.None;
        expect(pebble.isVirtual()).toBe(false);
    });
});