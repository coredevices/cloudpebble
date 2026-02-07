/*
 * TINF - Tiny Inflate Library wrapper
 * Uses the inflator.js library from noVNC which bundles pako
 */

var TINF = function() {
    this._inflator = null;
};

TINF.prototype.init = function() {
    // Initialize using the inflator library
    if (typeof inflator !== 'undefined' && inflator.Inflate) {
        this._inflator = new inflator.Inflate();
    }
};

TINF.prototype.reset = function() {
    if (this._inflator && this._inflator.reset) {
        this._inflator.reset();
    }
};

TINF.prototype.uncompress = function(data, offset) {
    if (this._inflator) {
        try {
            var input = data.slice(offset);
            return this._inflator.inflate(input, true); // true = flush
        } catch (e) {
            console.error('TINF uncompress error:', e);
            return data.slice(offset);
        }
    }
    
    // Fallback: return raw data
    console.warn('TINF: inflator not available');
    return data.slice(offset);
};

// Export for noVNC
window.TINF = TINF;
